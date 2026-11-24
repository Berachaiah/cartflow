"""Notifications that are actually delivered: a row in the bell, and mail.

WHY BOTH, AND WHY IN THIS ORDER. The row is the guarantee — it survives a mail
server that is down, a mailbox that is full, or a user who has turned mail off.
The email is the courtesy copy that reaches someone who is not in the app. So the
row is written and flushed first, the send is attempted second, and a failure is
logged rather than raised: a receipt that failed to send must never turn a
successful payment into a 500 for the buyer, because the money has already moved.

WHY `emailed_at` IS SET ONLY ON SUCCESS. `send_email` raises on a non-2xx SMTP
reply; if it returns, the server accepted the message. Storing that timestamp is
what makes "did they actually get told" answerable later without guessing from
logs that have rotated away.

WHY THE MESSAGE TEXT IS BUILT HERE, ONCE. The same order summary appears in the
in-app row and the email body. Building it twice is how a receipt ends up saying
₦12,500 in the bell and ₦12,500.00 in the mail, or listing an item the email
dropped. `_order_summary()` is the single source and both render from it.

WHAT IS NOT SENT. No promotional mail, no "check out these products", nothing the
user did not cause. Every mail here is transactional and triggered by that
user's own action, which is what keeps it outside the consent and unsubscribe
rules for marketing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email_templates import render_email
from app.integrations.smtp_client import send_email
from app.models.notification import Notification, NotificationKind
from app.models.payment import Payment
from app.models.product import Product
from app.models.organization import Organization
from app.models.user import User

logger = logging.getLogger("cartflow.notifications")

# kind -> (email template, subject). A kind with no entry is in-app only, which
# is a legitimate choice for noisy events (a like) and for events whose email
# would be spam (every message in a conversation).
EMAIL_FOR: dict[str, tuple[str, str]] = {
    NotificationKind.ORDER_PAID.value: ("order_confirmation.html", "Order confirmed"),
    NotificationKind.ORDER_SOLD.value: ("order_sold.html", "You made a sale"),
    NotificationKind.PAYMENT_FAILED.value: ("payment_failed.html", "Your payment did not go through"),
}

BODY_LIMIT = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def money(amount: int | float | str, currency: str = "NGN") -> str:
    """`12500` -> `₦12,500`. Naira prices are whole numbers, so no decimals."""
    symbol = {"NGN": "₦", "USD": "$", "GBP": "£", "EUR": "€"}.get(currency.upper(), "")
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return f"{symbol}{amount}"
    return f"{symbol}{value:,.0f}"


def order_summary(items: list[dict]) -> str:
    """One line per item, quantity included, for both the row and the email."""
    if not items:
        return "Your order"
    parts = []
    for line in items[:12]:
        qty = int(line.get("qty") or 1)
        name = str(line.get("name") or line.get("slug") or "Item")
        parts.append(f"{name} × {qty}" if qty > 1 else name)
    if len(items) > 12:
        parts.append(f"and {len(items) - 12} more")
    return ", ".join(parts)


async def push(
    db: AsyncSession,
    *,
    user: User,
    kind: str,
    title: str,
    body: str,
    url: str | None = None,
    actor_id: uuid.UUID | None = None,
    email_context: dict | None = None,
) -> Notification:
    """Write the row, then try the email. Never raises because of the email.

    Does not commit: the caller owns the transaction, so a payment that fails to
    settle after this point does not leave a row claiming it did. Callers that
    are not inside a transaction should `await db.commit()`.
    """
    row = Notification(
        user_id=user.id,
        kind=kind,
        title=title[:140],
        body=body[:BODY_LIMIT],
        url=url,
        actor_id=actor_id,
    )
    db.add(row)
    await db.flush()

    template_subject = EMAIL_FOR.get(kind)
    if template_subject and getattr(user, "email", None):
        template, subject = template_subject
        settings = get_settings()
        if getattr(settings, "SMTP_HOST", None):
            try:
                html = render_email(
                    template,
                    display_name=user.display_name,
                    title=title,
                    summary=body,
                    cta_url=f"{settings.APP_BASE_URL.rstrip('/')}{url or '/'}",
                    **(email_context or {}),
                )
                await send_email(to=user.email, subject=subject, html=html)
                row.emailed_at = _now()
            except Exception:  # noqa: BLE001 — any transport error is non-fatal here
                # Money already moved (or the message is already stored). A
                # missing courtesy copy is a degraded notification, not a failed
                # order, so this is logged with the recipient for reconciliation
                # and the row stays un-emailed on purpose.
                logger.exception(
                    "notification email failed kind=%s to=%s notification=%s",
                    kind,
                    user.email,
                    row.id,
                )
        else:
            # No SMTP configured: the in-app row is the whole notification, and
            # the build log says so once rather than pretending mail went out.
            logger.info("SMTP not configured; in-app notification only for %s", user.email)

    return row


async def _seller_map(db: AsyncSession, items: list[dict]) -> dict[str, User]:
    """slug -> the user who owns the shop selling it.

    Read from `products.organization_id -> organizations.owner_user_id` at
    notification time rather than stored on the payment: a shop that changes
    hands between order and settlement still needs the alert going to whoever
    owns the listing, and the payment's JSON is a price snapshot, not a roster.
    """
    slugs = [str(line.get("slug") or "") for line in items if line.get("slug")]
    if not slugs:
        return {}
    rows = (
        await db.execute(
            select(Product.slug, Organization.owner_user_id)
            .join(Organization, Organization.id == Product.organization_id)
            .where(Product.slug.in_(slugs))
        )
    ).all()
    owner_ids = {owner for _, owner in rows if owner}
    if not owner_ids:
        return {}
    users = (await db.execute(select(User).where(User.id.in_(owner_ids)))).scalars().all()
    by_id = {user.id: user for user in users}
    return {slug: by_id[owner] for slug, owner in rows if owner in by_id}


async def notify_order_paid(db: AsyncSession, *, payment: Payment) -> int:
    """Announce one successful payment: buyer receipt + one alert per seller.

    Returns the number of notifications written. Idempotency is inherited from
    `payments.settle()`, which returns early on an already-successful row — the
    webhook can arrive twice without sending the buyer a second receipt.
    """
    items = list(payment.items or [])
    total = money(payment.amount, payment.currency)
    summary = order_summary(items)

    buyer = payment.user
    if buyer is not None:
        await push(
            db,
            user=buyer,
            kind=NotificationKind.ORDER_PAID.value,
            title=f"Payment received — {total}",
            body=(
                f"{summary}. Reference {payment.reference}. "
                "The seller has been told and will confirm your order."
            ),
            url="/orders",
            email_context={
                "order_reference": payment.reference,
                "total_text": total,
                "items": items,
                "currency": payment.currency,
                "paid_at": payment.paid_at,
            },
        )

    seller_by_slug = await _seller_map(db, items)
    # One alert per SELLER, not per item: a shop that sold three things in one
    # checkout has one order to fulfil, and three identical emails would read
    # as three orders.
    lines_by_seller: dict[uuid.UUID, list[dict]] = {}
    for line in items:
        owner = seller_by_slug.get(str(line.get("slug") or ""))
        if owner is not None:
            lines_by_seller.setdefault(owner.id, []).append(line)

    owners = {user.id: user for user in seller_by_slug.values()}
    written = 1 if buyer is not None else 0
    for seller_id, mine in lines_by_seller.items():
        seller = owners[seller_id]
        subtotal = sum(int(line.get("line_total") or 0) for line in mine)
        await push(
            db,
            user=seller,
            kind=NotificationKind.ORDER_SOLD.value,
            title=f"New order — {money(subtotal, payment.currency)}",
            body=(
                f"{order_summary(mine)}. Reference {payment.reference}. "
                "Open your orders to confirm it and arrange pickup or delivery."
            ),
            url="/orders",
            actor_id=getattr(buyer, "id", None),
            email_context={
                "order_reference": payment.reference,
                "total_text": money(subtotal, payment.currency),
                "items": mine,
                "currency": payment.currency,
                "buyer_name": getattr(buyer, "display_name", "A buyer"),
            },
        )
        written += 1

    await db.commit()
    return written


async def notify_payment_failed(db: AsyncSession, *, payment: Payment) -> int:
    """Tell the buyer a charge did not go through — once per failed row."""
    buyer = payment.user
    if buyer is None:
        return 0
    total = money(payment.amount, payment.currency)
    await push(
        db,
        user=buyer,
        kind=NotificationKind.PAYMENT_FAILED.value,
        title="Payment did not go through",
        body=(
            f"We could not complete your payment of {total} "
            f"(reference {payment.reference}). Nothing was charged — "
            "you can try again from your cart."
        ),
        url="/orders",
        email_context={
            "order_reference": payment.reference,
            "total_text": total,
            "items": list(payment.items or []),
            "currency": payment.currency,
        },
    )
    await db.commit()
    return 1


async def list_for(db: AsyncSession, *, user: User, limit: int = 30) -> list[Notification]:
    rows = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def unread_count(db: AsyncSession, *, user: User) -> int:
    return int(
        (
            await db.execute(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user.id, Notification.read_at.is_(None)
                )
            )
        ).scalar()
        or 0
    )


async def mark_read(db: AsyncSession, *, user: User, notification_id: uuid.UUID | None = None) -> int:
    """Mark one, or every unread row, as read. Returns how many changed."""
    stmt = select(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    )
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    rows = (await db.execute(stmt)).scalars().all()
    now = _now()
    for row in rows:
        row.read_at = now
    await db.commit()
    return len(rows)
