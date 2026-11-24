"""The activity store behind the bell (docs/product/11-activity-and-notifications.md).

WHY A TABLE AND NOT DERIVED ROWS. Until now /notifications rendered the follow
graph, because a follow edge is the one event this schema could already prove.
That works for "X followed you" and for nothing else: a payment, an order status
change or a message has no durable record of *having been announced*. Deriving
those from their own tables only works while the event is still visible — a
payment row says money moved, not that the buyer was told.

WHAT IS DELIBERATELY NOT HERE.
  * No push tokens. Doc §14 wants web push; that needs a subscriptions table and
    a VAPID key pair, and a column for it here would be dead weight.
  * No retry queue. An email that fails is logged and the in-app row still
    exists, which is the honest guarantee: the notification is the row, the mail
    is a courtesy copy.
  * No soft delete on read clearing. `read_at` is the state; clearing is a
    delete the user asked for, which is a separate endpoint.

`emailed_at` is stored rather than inferred: "did the buyer actually get mail"
is the first question when someone says they never heard about an order, and an
SMTP 250 is the only evidence that can answer it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationKind(str, enum.Enum):
    """The event that caused the row.

    Kept as a string column, not a native enum: adding a kind is a code change,
    and a Postgres enum would need a migration (and a lock) for every new one.
    The value is what the template switches on, so the set must stay explicit.
    """

    ORDER_PAID = "order_paid"        # buyer: your payment went through
    ORDER_SOLD = "order_sold"        # seller: someone bought from your shop
    PAYMENT_FAILED = "payment_failed"  # buyer: the charge did not go through
    MESSAGE = "message"              # reserved: new-message alert


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        # The only query this table serves: one user's inbox, newest first.
        Index("ix_notifications_user_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # The sentence and the detail are stored, not rendered from the event at
    # read time. An order's contents can change (a line refunded, a name
    # edited); the notification must keep saying what it said when it happened.
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Where tapping it goes. Relative on purpose: the same row is read from
    # localhost and from production, and an absolute URL baked at write time
    # would send a local one to a deployed inbox.
    url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Who caused it, when the answer is a person (a seller, a message sender).
    # Nullable and ON DELETE SET NULL: losing the actor must not delete the fact.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(lazy="joined", foreign_keys=[user_id])  # noqa: F821
    actor: Mapped["User | None"] = relationship(  # noqa: F821
        lazy="joined", foreign_keys=[actor_id]
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Notification {self.kind} to={self.user_id}>"
