"""
Payments — one row per checkout attempt (Flutterwave).

Why this table exists at all, given doc 14 §25 asks for six order tables: a
payment is the one row the money actually needs. Everything else in that chapter
(order status history, deliveries, disputes, refunds) describes what happens
AFTER a payment succeeds, and each of those is its own feature. This table is
what makes the step that spends real money observable: a reference the buyer can
be shown, an amount computed from the catalogue, and a status that only ever
changes on the provider's verdict.

Three choices worth keeping:

*`items` is JSON, not an order_items table.* It is a SNAPSHOT — the name, price
and quantity as they were at the moment of checkout. That is deliberately not a
foreign key into `products`: a product's price changes, and a receipt must keep
printing the price that was charged. An order_items table becomes right when
orders get fulfilment states; a receipt does not need one.

*`reference` is ours, generated here, and it is the idempotency key.* Flutterwave
is asked to create a link for this exact `tx_ref` and verification looks the same
reference up. Two clicks on Checkout make two rows and two references, so a
partially-completed checkout can never be settled twice.

*`status` is a provider verdict, not a wish.* `pending` is what the row starts as;
only a successful verify call (server-side, against Flutterwave) may move it to
`successful`. The browser's `?status=successful` redirect parameter is never
trusted — see app/services/flutterwave.py.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import (
    Base,
    PublicIdMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class PaymentStatus(str, enum.Enum):
    """`pending` → `successful` | `failed` | `cancelled`.

    `failed` and `cancelled` are terminal and kept, not deleted: a buyer asking
    "did my card get charged?" is answered by the row that says it did not.
    """

    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Payment(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        # One buyer's history, newest first — the only list query this table has.
        Index("ix_payments_user_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="flutterwave")
    # Our tx_ref. Unique because it is what verification is keyed on.
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Flutterwave's own transaction id, filled in when verification succeeds.
    provider_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Numeric, not float: money. Two decimals because NGN is kobo-2 and the
    # provider charges in major units.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.PENDING.value, index=True
    )

    # [{slug, name, business, qty, unit_price, line_total, image}] — see module docstring.
    items: Mapped[list | None] = mapped_column(JSON, nullable=True)

    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)

    # The hosted checkout URL Flutterwave returned. Stored so a buyer who closes
    # the tab can be sent back to the same page instead of a new charge.
    checkout_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(lazy="joined")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Payment {self.reference} {self.status} {self.amount}>"
