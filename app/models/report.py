"""
Abuse reports — doc 10 §23.

A report is a durable record, not a notification. The user's requirement was
"store reports and email admins", in that order, and the order matters: the row
is committed first and the mail is best-effort on top. An SMTP failure must never
lose a harassment report, so `emailed_at` stays NULL and the row is still there
to be found — which is also why the send is not wrapped in a way that would
roll the insert back.

Reports are append-only from the user's side: there is no edit and no delete
endpoint. `status` moves open → reviewed by an admin, and admins live in their
own table (not yet modeled — see app/models/user.py's header), so there is no
`reviewed_by` FK to point anywhere useful yet.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import (
    Base,
    PublicIdMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ReportReason(str):
    """§23's four reasons, verbatim. Plain String(30), so this can grow without
    a migration — same pattern as MediaKind."""

    SPAM = "spam"
    HARASSMENT = "harassment"
    FRAUD = "fraud"
    ABUSE = "abuse"


# The set the API validates against. A tuple rather than an Enum so the column
# stays a plain string and the schema layer can list it for the UI.
REPORT_REASONS: tuple[str, ...] = (
    ReportReason.SPAM,
    ReportReason.HARASSMENT,
    ReportReason.FRAUD,
    ReportReason.ABUSE,
)

# Human labels for the report sheet and the admin email, kept beside the values
# so the two never disagree.
REPORT_REASON_LABELS: dict[str, str] = {
    ReportReason.SPAM: "Spam",
    ReportReason.HARASSMENT: "Harassment",
    ReportReason.FRAUD: "Fraud or a scam",
    ReportReason.ABUSE: "Abuse",
}


class ReportStatus(str):
    OPEN = "open"
    REVIEWED = "reviewed"


class Report(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin):
    __tablename__ = "reports"

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Indexed because the question an admin asks is "what else has been reported
    # about this account" — a pattern of four spam reports is the signal, not any
    # one of them.
    reported_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Where it was reported from, when that is a thread. SET NULL rather than
    # CASCADE: deleting a conversation must not erase the report about it.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )

    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReportStatus.OPEN
    )

    # NULL means the admin email has not gone out — either it has not been tried
    # yet or SMTP failed. Either way the report is not lost, and the gap is
    # visible in the table rather than only in the logs.
    emailed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Report {self.public_id} ({self.reason})>"
