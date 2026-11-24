"""
Payments — pricing a cart, starting a Flutterwave checkout, and settling it.

This is the only module that may change a `payments` row's status, and it only
changes it in `settle()`, from the provider's verified answer.

The flow, end to end:

  Shop → POST /api/payments/checkout {items:[{slug, qty}]}
       → `price_lines()` re-reads the catalogue and builds the receipt
       → a `pending` Payment row with our own reference
       → `flutterwave.create_payment_link()` → hosted checkout URL
       → browser leaves for Flutterwave

  Flutterwave → /payments/callback?tx_ref=…&status=…
              → `settle()` asks Flutterwave what actually happened
              → `successful` (with the amount checked) or still pending

  Flutterwave → POST /webhooks/flutterwave (signed with verif-hash)
              → the same `settle()`, so the row is correct even if the buyer
                closes the tab before the redirect happens

Why the price is recomputed here rather than accepted from the browser: the cart
is a list of `{slug, qty}` in localStorage, so the client has no amount to send
in the first place. That is the design, not an accident — a cart that posted a
total would make `POST /api/payments/checkout` a "charge me ₦1 for this laptop"
endpoint.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.payment import Payment, PaymentStatus
from app.models.product import Product
from app.models.user import User
from app.services import flutterwave, squad
from app.services.catalog import list_products

logger = logging.getLogger("cartflow.payments")

settings = get_settings()

# A cart larger than this is a script, not a shopper. The cap also bounds the
# catalogue lookups one request can trigger.
MAX_LINES = 40
# Per-line ceiling, matching the Shop's own quantity control.
MAX_QTY = 99


def new_reference() -> str:
    """Our tx_ref. Prefix makes a reference recognisable in the Flutterwave
    dashboard, where every other integration's tx_refs are mixed in."""
    return f"cf-{uuid.uuid4().hex[:20]}"


async def price_lines(db: AsyncSession, raw_items: object) -> list[dict]:
    """Turn `[{slug, qty}]` into priced lines, or refuse.

    Everything the receipt shows — name, business, unit price — is read from the
    catalogue at this moment. A slug that is no longer listed or has sold out is
    an error rather than a silently dropped line: charging for three of four
    items and saying nothing is the failure mode this guards against.
    """
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationAppError("Your cart is empty.")

    wanted: dict[str, int] = {}
    for item in raw_items[:MAX_LINES]:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        try:
            qty = int(item.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if not slug or qty <= 0:
            continue
        wanted[slug] = min(wanted.get(slug, 0) + qty, MAX_QTY)

    if not wanted:
        raise ValidationAppError("Your cart is empty.")

    catalogue = {p["slug"]: p for p in await list_products(db)}
    lines: list[dict] = []
    for slug, qty in wanted.items():
        product = catalogue.get(slug)
        if product is None:
            raise ValidationAppError(
                "An item in your cart is no longer listed. Remove it and try again."
            )
        stock = int(product.get("stock") or 0)
        if stock <= 0:
            raise ValidationAppError(f"{product['name']} just went out of stock.")
        if stock < qty:
            raise ValidationAppError(
                f"Only {stock} left of {product['name']}. Lower the quantity and try again."
            )
        unit = int(product["price"])
        lines.append(
            {
                "slug": slug,
                "name": product["name"],
                "business": product.get("business") or "CartFlow seller",
                "qty": qty,
                "unit_price": unit,
                "line_total": unit * qty,
                "image": product.get("image"),
            }
        )
    return lines


def total_of(lines: list[dict]) -> int:
    """In naira, integer. The provider is charged in major units with two
    decimals; the catalogue prices are whole naira, so this is exact."""
    return sum(int(line["line_total"]) for line in lines)


def _amount_text(amount: Decimal) -> str:
    return f"{amount:.2f}"


def enabled_providers() -> list[dict]:
    """The gateways the Shop may offer. Read from settings so the picker in
    `shop.html` and the `provider` check in `start_checkout` cannot disagree."""
    return settings.enabled_payment_providers


def _resolve_provider(provider: str | None) -> dict:
    """The provider dict for `provider`, or refuse.

    The list is the allow-list: an unknown string is a 422 rather than a
    fallback, because silently charging through a different gateway than the one
    the buyer chose is exactly the kind of surprise money must not have.
    """
    available = {p["key"]: p for p in enabled_providers()}
    wanted = (provider or settings.PAYMENT_PROVIDER or "flutterwave").strip().lower()
    if wanted not in available:
        if not available:
            raise ValidationAppError(
                "Card payments are not configured on this deployment yet."
            )
        raise ValidationAppError("That payment method is not available.")
    return available[wanted]


async def _create_link(payment: Payment, *, provider: str, redirect_url: str) -> str:
    """Ask the chosen gateway for a hosted checkout URL."""
    customer = {"email": payment.customer_email, "name": payment.customer_name}
    if provider == "squad":
        return await squad.create_payment_link(
            reference=payment.reference,
            amount=Decimal(payment.amount),
            currency=payment.currency,
            redirect_url=redirect_url,
            customer=customer,
        )
    return await flutterwave.create_payment_link(
        reference=payment.reference,
        amount=_amount_text(Decimal(payment.amount)),
        currency=payment.currency,
        redirect_url=redirect_url,
        customer=customer,
    )


async def start_checkout(
    db: AsyncSession,
    *,
    user: User,
    raw_items: object,
    provider: str | None = None,
) -> Payment:
    """Create the pending row and the hosted checkout URL for it."""
    chosen = _resolve_provider(provider)
    key = chosen["key"]

    lines = await price_lines(db, raw_items)
    payment = Payment(
        user_id=user.id,
        provider=key,
        reference=new_reference(),
        amount=Decimal(total_of(lines)),
        currency=(
            settings.SQUAD_CURRENCY if key == "squad" else settings.FLUTTERWAVE_CURRENCY
        ),
        status=PaymentStatus.PENDING.value,
        items=lines,
        customer_email=user.email,
        customer_name=user.display_name,
    )
    db.add(payment)
    # Committed BEFORE the provider call: if Flutterwave times out we still hold
    # the reference, and the webhook can settle a row that exists. A row created
    # after the call would leave an orphaned payment with nothing to match.
    await db.commit()
    await db.refresh(payment)

    redirect_url = f"{settings.APP_BASE_URL.rstrip('/')}/payments/callback"
    payment.checkout_url = await _create_link(
        payment, provider=key, redirect_url=redirect_url
    )
    await db.commit()
    await db.refresh(payment)
    return payment


async def by_reference(db: AsyncSession, reference: str) -> Payment | None:
    result = await db.execute(select(Payment).where(Payment.reference == reference))
    return result.scalar_one_or_none()


async def settle(db: AsyncSession, *, payment: Payment) -> Payment:
    """Ask Flutterwave what happened to `payment`, then record it.

    Idempotent: a settled row is returned untouched, so a webhook arriving after
    the redirect (or twice) cannot charge anything twice or double-decrement
    stock.

    The two checks that matter:
      * status — `successful`/`completed` from the provider's own record;
      * amount and currency — a verified transaction for a DIFFERENT amount is
        not this payment, whatever its reference says.
    """
    if payment.status == PaymentStatus.SUCCESSFUL.value:
        return payment

    result = await verify_with_provider(payment)
    status = result.get("status") or ""

    if not _is_success(payment.provider, status):
        # Terminal failures are recorded; an empty status means the buyer never
        # paid, so the row stays pending and can still be completed later.
        if status in {"failed", "cancelled"}:
            payment.status = (
                PaymentStatus.FAILED.value
                if status == "failed"
                else PaymentStatus.CANCELLED.value
            )
            await db.commit()
            await db.refresh(payment)
        return payment

    try:
        paid = Decimal(str(result.get("amount")))
    except (InvalidOperation, TypeError):
        logger.warning("flutterwave paid without a usable amount ref=%s", payment.reference)
        return payment

    currency = (result.get("currency") or "").upper()
    if paid != Decimal(payment.amount) or currency != payment.currency.upper():
        # Money moved, but not for this receipt. Record it as pending and log:
        # an operator must reconcile it by hand, and the buyer must not get an
        # order for an amount that was never charged.
        logger.error(
            "amount mismatch ref=%s expected=%s %s got=%s %s",
            payment.reference,
            payment.amount,
            payment.currency,
            paid,
            currency,
        )
        return payment

    payment.status = PaymentStatus.SUCCESSFUL.value
    payment.provider_reference = result.get("provider_reference")
    payment.paid_at = datetime.now(timezone.utc)
    await _take_stock(db, payment)
    await db.commit()
    await db.refresh(payment)
    return payment


async def verify_with_provider(payment: Payment) -> dict:
    """The provider's own record of this payment, normalised.

    Dispatched on what the ROW says, not on what any request asked for: a
    Flutterwave payment is only ever verified at Flutterwave, whatever a webhook
    body or a callback claims.
    """
    if payment.provider == "squad":
        return await squad.verify_transaction(payment.reference)
    return await flutterwave.verify_transaction(payment.reference)


def _is_success(provider: str, status: str) -> bool:
    if provider == "squad":
        return squad.is_success(status)
    return flutterwave.is_success(status)


async def _take_stock(db: AsyncSession, payment: Payment) -> None:
    """Decrement stock and count the sale, once.

    Called only from the successful transition, which `settle()` guarantees
    happens once per row. A line whose product has since been deleted is
    skipped rather than raising: the money has already moved by this point, and
    failing here would strand a paid payment in `pending`.
    """
    for line in payment.items or []:
        product = (
            await db.execute(select(Product).where(Product.slug == line.get("slug")))
        ).scalar_one_or_none()
        if product is None:
            continue
        qty = int(line.get("qty") or 0)
        product.stock = max(0, int(product.stock or 0) - qty)
        product.sold_count = int(product.sold_count or 0) + qty


async def for_user(db: AsyncSession, user_id: uuid.UUID, *, limit: int = 50) -> list[Payment]:
    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def to_receipt(payment: Payment) -> dict:
    """The shape the Orders page renders. Money is formatted here, once, so the
    page and any later email cannot disagree about a price."""
    items = payment.items or []
    return {
        "reference": payment.reference,
        "status": payment.status,
        # Which gateway took the money. Shown on the receipt so a buyer can match
        # the charge on their bank statement.
        "provider": payment.provider,
        "provider_label": {"squad": "Squad"}.get(payment.provider, "Flutterwave"),
        "amount": int(payment.amount),
        "amount_text": f"₦{int(payment.amount):,}",
        "currency": payment.currency,
        "created_at": payment.created_at,
        "paid_at": payment.paid_at,
        "items": items,
        "item_count": sum(int(i.get("qty") or 0) for i in items),
        "business": items[0].get("business") if items else None,
        # Which Orders tab this row belongs in. Fulfilment states do not exist
        # yet, so a paid payment stays "current" rather than claiming an order
        # was completed; failed/cancelled attempts are history, not current work.
        "tab": (
            "current"
            if payment.status in (PaymentStatus.PENDING.value, PaymentStatus.SUCCESSFUL.value)
            else "cancelled"
        ),
        "title": items[0].get("name") if len(items) == 1 else (
            f"{items[0].get('name')} + {len(items) - 1} more" if items else "Order"
        ),
    }


async def require_by_reference(db: AsyncSession, reference: str) -> Payment:
    payment = await by_reference(db, reference)
    if payment is None:
        raise NotFoundError("That payment could not be found.")
    return payment
