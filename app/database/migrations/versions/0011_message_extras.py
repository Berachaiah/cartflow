"""message pins + chat wallpapers

Revision ID: 0011_message_extras
Revises: 0010_disappearing_messages
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_message_extras"
down_revision: Union[str, None] = "0010_disappearing_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "message_pins",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("pinned_by_id", sa.Uuid(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("conversation_id", "message_id"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pinned_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_message_pins_conversation", "message_pins", ["conversation_id"])

    op.create_table(
        "chat_wallpapers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False, server_default="preset"),
        sa.Column("preset", sa.String(20), nullable=True),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column("focus_x", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("focus_y", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("ratio", sa.String(8), nullable=True),
        sa.Column("dim", sa.Integer(), nullable=False, server_default="0"),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_chat_wallpapers_user_chat", "chat_wallpapers", ["user_id", "conversation_id"], unique=True)
    op.create_index(
        "ix_chat_wallpapers_user_default", "chat_wallpapers", ["user_id"], unique=True,
        postgresql_where=sa.text("conversation_id IS NULL"),
        sqlite_where=sa.text("conversation_id IS NULL"),
    )

    # Supabase exposes `public` through its Data API: keep these closed, as the other tables are.
    if op.get_bind().dialect.name == "postgresql":
        for t in ("message_pins", "chat_wallpapers"):
            op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_chat_wallpapers_user_default", table_name="chat_wallpapers")
    op.drop_index("ix_chat_wallpapers_user_chat", table_name="chat_wallpapers")
    op.drop_table("chat_wallpapers")
    op.drop_index("ix_message_pins_conversation", table_name="message_pins")
    op.drop_table("message_pins")
