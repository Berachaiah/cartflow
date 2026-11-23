"""The pinned product bar and price offers (migration 0012).

Every entry point goes through `messaging_service.require_participant`, so a
stranger or a blocked pair gets the same 404 as everywhere else in messaging.
Offers are real messages (kind "offer") sent through `send_message`, so blocks,
the send limit, request rules and disappearing timers all apply unchanged.
Mutations lock the conversation's `conversation_products` row, which serialises
two people answering the same offer at the same instant.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.timeutils import utc_now
from app.models.conversation import Message, MessageKind
from app.models.message_extras import ConversationProduct
from app.models.user import User
from app.services import catalog
from app.services import messaging as messaging_service
from app.services.message_extras import _aware, _party_ids

OFFER = MessageKind.OFFER
PENDING, ACCEPTED, COUNTERED, DECLINED, WITHDRAWN = (
    "pending", "accepted", "countered", "declined", "withdrawn",
)


# ------------------------------------------------------------- products ----


def _image_of(p: dict) -> str | None:
    for key in ("image", "img", "image_url", "photo", "thumb", "cover"):
        if p.get(key):
            return p[key]
    imgs = p.get("images")
    return imgs[0] if imgs else None


def _stock_label(stock: int) -> str:
    return "Out of stock" if stock <= 0 else "Low stock" if stock <= 5 else "In stock"


def _card(p: dict) -> dict:
    stock = int(p.get("stock") or 0)
    return {
        "slug": p["slug"], "available": True, "name": p["name"], "price": int(p["price"]),
        "price_label": catalog.naira(p["price"]), "image_url": _image_of(p),
        "in_stock": stock > 0, "stock_label": _stock_label(stock),
    }


def product_card(slug: str) -> dict:
    try:
        return _card(catalog.get_product(slug))
    except NotFoundError:
        return {"slug": slug, "available": False, "name": "Product unavailable", "price": 0,
                "price_label": "", "image_url": None, "in_stock": False, "stock_label": "Unavailable"}


def catalog_items() -> list[dict]:
    return [_card(p) for p in catalog.list_products()][:40]


# --------------------------------------------------------------- helpers ----


async def _lock_row(db: AsyncSession, conversation_id: uuid.UUID) -> ConversationProduct | None:
    return (
        await db.execute(
            select(ConversationProduct)
            .where(ConversationProduct.conversation_id == conversation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _offers_with(db: AsyncSession, conversation_id: uuid.UUID, status: str, slug: str) -> list[Message]:
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.kind == OFFER,
                Message.offer_status == status,
                Message.shared_product_slug == slug,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.created_at.desc())
        )
    ).scalars().all()
    now = utc_now()
    return [m for m in rows if m.expires_at is None or _aware(m.expires_at) > now]


def _brief(m: Message | None, viewer_id: uuid.UUID) -> dict | None:
    if m is None:
        return None
    return {"public_id": str(m.public_id), "price": m.offer_price, "status": m.offer_status,
            "is_mine": m.sender_id == viewer_id}


async def _other_user(db: AsyncSession, conversation_id: uuid.UUID, viewer_id: uuid.UUID) -> User:
    ids = (await _party_ids(db, conversation_id)) - {viewer_id}
    other = await db.get(User, next(iter(ids))) if ids else None
    if other is None:
        raise NotFoundError("That conversation isn't available.")
    return other


def _check_price(price: int, listed: int) -> None:
    if price <= 0:
        raise ValidationAppError("Enter an amount above ₦0.", fields={"price": "Must be above zero."})
    if listed and price > listed:
        raise ValidationAppError(
            f"An offer can't be above the listed price of {catalog.naira(listed)}.",
            fields={"price": "Above the listed price."},
        )


async def deal_payload(db: AsyncSession, *, viewer_id: uuid.UUID, conversation) -> dict:
    row = await db.get(ConversationProduct, conversation.id)
    if row is None:
        return {"product": None, "seller_is_me": False, "sold": False, "can_offer": False,
                "pending_offer": None, "accepted_offer": None}
    card = product_card(row.product_slug)
    pending = await _offers_with(db, conversation.id, PENDING, row.product_slug)
    accepted = await _offers_with(db, conversation.id, ACCEPTED, row.product_slug)
    seller_is_me = row.seller_id == viewer_id
    can_offer = (
        row.seller_id is not None and not seller_is_me and not row.sold
        and card["available"] and card["in_stock"] and not pending and not accepted
    )
    return {
        "product": card, "seller_is_me": seller_is_me, "sold": row.sold, "can_offer": can_offer,
        "pending_offer": _brief(pending[0] if pending else None, viewer_id),
        "accepted_offer": _brief(accepted[0] if accepted else None, viewer_id),
    }


# ------------------------------------------------------- pinned product ----


async def get_deal(db: AsyncSession, *, viewer: User, public_id: uuid.UUID) -> dict:
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    return await deal_payload(db, viewer_id=viewer.id, conversation=conversation)


async def set_product(db: AsyncSession, *, viewer: User, public_id: uuid.UUID, slug: str, role: str):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    if role not in ("seller", "buyer"):
        raise ValidationAppError("Say whether you're buying or selling.", fields={"role": "Invalid role."})
    product = catalog.get_product(slug)  # NotFoundError for an unknown slug
    party = await _party_ids(db, conversation.id)
    row = await _lock_row(db, conversation.id)
    if row is None:
        other = next(iter(party - {viewer.id}), None)
        db.add(ConversationProduct(
            conversation_id=conversation.id, product_slug=product["slug"],
            seller_id=viewer.id if role == "seller" else other, sold=False,
        ))
    elif row.product_slug != product["slug"]:
        if await _offers_with(db, conversation.id, PENDING, row.product_slug):
            raise ConflictError("Answer or cancel the open offer before changing the pinned product.")
        row.product_slug, row.sold = product["slug"], False
    await db.flush()
    return await deal_payload(db, viewer_id=viewer.id, conversation=conversation), party


async def clear_product(db: AsyncSession, *, viewer: User, public_id: uuid.UUID):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    party = await _party_ids(db, conversation.id)
    row = await _lock_row(db, conversation.id)
    if row is not None:
        if await _offers_with(db, conversation.id, PENDING, row.product_slug):
            raise ConflictError("Answer or cancel the open offer before removing the pinned product.")
        await db.delete(row)
        await db.flush()
    return await deal_payload(db, viewer_id=viewer.id, conversation=conversation), party


async def set_sold(db: AsyncSession, *, viewer: User, public_id: uuid.UUID, sold: bool):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    party = await _party_ids(db, conversation.id)
    row = await _lock_row(db, conversation.id)
    if row is None:
        raise NotFoundError("No product is pinned to this chat.")
    if row.seller_id != viewer.id:
        raise ForbiddenError("Only the seller can mark this as sold.")
    row.sold = sold
    if sold:
        for m in await _offers_with(db, conversation.id, PENDING, row.product_slug):
            m.offer_status = DECLINED
    await db.flush()
    return await deal_payload(db, viewer_id=viewer.id, conversation=conversation), party


# --------------------------------------------------------------- offers ----


async def _send_offer(db, *, viewer: User, conversation, slug: str, price: int, listed: int) -> Message:
    other = await _other_user(db, conversation.id, viewer.id)
    result = await messaging_service.send_message(
        db, sender=viewer, username=other.username, kind=OFFER,
        body=f"Offer: {catalog.naira(price)}", shared_product_slug=slug,
    )
    m = result.message
    m.offer_price, m.offer_listed, m.offer_status = price, listed, PENDING
    await db.flush()
    return m


async def make_offer(db: AsyncSession, *, viewer: User, public_id: uuid.UUID, price: int):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    row = await _lock_row(db, conversation.id)
    if row is None:
        raise NotFoundError("Pin a product to this chat before making an offer.")
    if row.seller_id is None or row.seller_id == viewer.id:
        raise ForbiddenError("Only the buyer can start an offer. Use Counter on an offer you receive.")
    card = product_card(row.product_slug)
    if row.sold or not card["available"] or not card["in_stock"]:
        raise ConflictError("This item isn't available right now.")
    _check_price(price, card["price"])
    if await _offers_with(db, conversation.id, PENDING, row.product_slug):
        raise ConflictError("There's already an open offer in this chat. Answer or cancel it first.")
    if await _offers_with(db, conversation.id, ACCEPTED, row.product_slug):
        raise ConflictError("An offer on this item was already accepted.")
    await _send_offer(db, viewer=viewer, conversation=conversation, slug=row.product_slug,
                      price=price, listed=card["price"])
    party = await _party_ids(db, conversation.id)
    return await deal_payload(db, viewer_id=viewer.id, conversation=conversation), party


async def respond(db: AsyncSession, *, viewer: User, public_id: uuid.UUID,
                  message_public_id: uuid.UUID, action: str, price: int | None = None):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    row = await _lock_row(db, conversation.id)
    m = (
        await db.execute(
            select(Message).where(
                Message.public_id == message_public_id,
                Message.conversation_id == conversation.id,
                Message.kind == OFFER,
                Message.deleted_at.is_(None),
            ).with_for_update(of=Message)
        )
    ).scalar_one_or_none()
    if row is None or m is None or (m.expires_at is not None and _aware(m.expires_at) <= utc_now()):
        raise NotFoundError("That offer isn't available.")
    if m.offer_status != PENDING:
        raise ConflictError("That offer has already been answered or cancelled.")

    if action == "withdraw":
        if m.sender_id != viewer.id:
            raise ForbiddenError("Only the person who made an offer can cancel it.")
        m.offer_status = WITHDRAWN
    else:
        if m.sender_id == viewer.id:
            raise ForbiddenError("You can't answer your own offer.")
        card = product_card(row.product_slug)
        if action in ("accept", "counter") and (row.sold or not card["available"] or not card["in_stock"]):
            raise ConflictError("This item isn't available right now.")
        if action == "accept":
            m.offer_status = ACCEPTED
        elif action == "decline":
            m.offer_status = DECLINED
        elif action == "counter":
            listed = m.offer_listed or card["price"]
            _check_price(price or 0, listed)
            m.offer_status = COUNTERED
            await db.flush()
            await _send_offer(db, viewer=viewer, conversation=conversation, slug=row.product_slug,
                              price=price, listed=listed)
        else:
            raise ValidationAppError("Unknown action.", fields={"action": "Unknown action."})
    await db.flush()
    party = await _party_ids(db, conversation.id)
    return await deal_payload(db, viewer_id=viewer.id, conversation=conversation), party
