"""message replies + reactions

Revision ID: 0017_message_replies
Revises: 0016_notifications
Create Date: 2026-11-24

Two gaps against every mainstream messenger: you could not quote a message, and
there was no way to react to one.

A reply stores a POINTER, not a copy of the quoted text — copying would go stale
the moment the original was deleted, and a quote of a deleted message should say
so. Reactions are keyed by (message, user, emoji) so a double-tap is idempotent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_message_replies"
down_revision: Union[str, None] = "0016_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reply_to_id", sa.Uuid(), nullable=True))
    op.create_index("ix_messages_reply_to_id", "messages", ["reply_to_id"])
    op.create_foreign_key(
        "fk_messages_reply_to_id",
        "messages",
        "messages",
        ["reply_to_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "message_reactions",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "user_id", "emoji"),
    )
    op.create_index("ix_message_reactions_user", "message_reactions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_message_reactions_user", table_name="message_reactions")
    op.drop_table("message_reactions")
    op.drop_constraint("fk_messages_reply_to_id", "messages", type_="foreignkey")
    op.drop_index("ix_messages_reply_to_id", table_name="messages")
    op.drop_column("messages", "reply_to_id")
