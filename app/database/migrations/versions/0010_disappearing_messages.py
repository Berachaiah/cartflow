"""disappearing messages: per-conversation timer + per-message expiry

Revision ID: 0010_disappearing_messages
Revises: 0009_messaging
Create Date: 2026-08-20

Messages disappear 48h after they are sent, WhatsApp-style: the timer lives on
the conversation, either participant can turn it off, and the value is frozen
onto each message when it is sent so a later change only governs later messages.
Three columns carry it:

* **`conversations.disappear_after_seconds`** — the timer for this thread, in
  seconds. Seconds rather than a bool so "let people pick 24h / 7 days" later is
  a value change, not a migration; V1 only ever writes 172800 (48h) or NULL
  (off). `server_default='172800'` so *existing* threads adopt the 48h default
  the moment this runs — the same default new threads get in the model. NULL is
  a real, distinct state (off), which is why the column is nullable despite the
  default.

* **`conversations.last_message_expires_at`** — a denormalised mirror, like the
  `last_message_*` columns beside it, so the inbox can blank a row whose last
  message has vanished without joining `messages`. No backfill: NULL is correct
  for every existing row (their last message predates the feature and never
  expires).

* **`messages.expires_at`** — when this message disappears, or NULL for "never".
  **Deliberately not backfilled.** Every message that already exists was sent
  before disappearing existed, so it must keep behaving as permanent; a backfill
  to `created_at + 48h` would silently delete conversation history the users
  believe is durable. Only messages sent after this migration carry an expiry.

`ix_messages_expires_at` turns the sweep's `WHERE expires_at <= now` from a
full-table scan into a range scan (NULLs — the permanent messages — sort out of
the way for free).

All three are plain ADD COLUMNs. SQLite supports ADD COLUMN, and a constant
`server_default` is valid there too, so this needs no dialect guard (same as
0008's and 0009's additive columns). The test suite builds its schema with
`Base.metadata.create_all`, not migrations, so this file and
app/models/conversation.py must stay in step.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010_disappearing_messages"
down_revision: Union[str, None] = "0009_messaging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing threads adopt the 48h default; new ones get it from the model.
    op.add_column(
        "conversations",
        sa.Column(
            "disappear_after_seconds",
            sa.Integer(),
            nullable=True,
            server_default="172800",  # 48h; DEFAULT_DISAPPEAR_SECONDS
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "last_message_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    # No backfill: NULL keeps every pre-existing message permanent.
    op.add_column(
        "messages", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_messages_expires_at", "messages", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_expires_at", table_name="messages")
    op.drop_column("messages", "expires_at")
    op.drop_column("conversations", "last_message_expires_at")
    op.drop_column("conversations", "disappear_after_seconds")
