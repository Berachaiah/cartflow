"""messaging: conversations, participants, messages, blocks, reports

Revision ID: 0009_messaging
Revises: 0008_user_full_name
Create Date: 2026-08-18

Doc 10 (Messaging) has been specified since V1.0 and unimplemented: `/messages`
rendered the *rules* of messaging because there was no table to put a thread in.
This creates the schema behind it.

Doc 10 §26 names six tables. This creates four of them plus `reports`, and the
folds are argued in app/models/conversation.py's module docstring rather than
repeated here. The short version: `message_requests` is
`conversations.status = 'pending'`, `message_reads` is
`conversation_participants.last_read_at`, and `message_attachments` is three
nullable columns on `messages`.

Three details worth noting:

* **`users.last_seen_at` is a plain ADD COLUMN.** Nullable, no backfill: NULL
  means "never seen in a live session", which is true of every existing row.
  SQLite supports ADD COLUMN, so this needs no dialect guard (same as 0008).

* **The FKs are created inline with the tables, not bolted on afterwards**, so
  the SQLite guard 0007_media needed does not apply to them — `CREATE TABLE ...
  REFERENCES` is fine on every dialect. The guard reappears only for the two
  self-referential FKs on `messages`/`conversations` if a future migration has to
  alter them.

* **`created_at`/`updated_at` carry `server_default=now()`** on every table here,
  matching TimestampMixin, so a raw INSERT from a script or a psql session is
  valid without naming them.

The test suite builds its schema with `Base.metadata.create_all`, not migrations,
so this file and app/models/conversation.py + app/models/report.py must stay in
step — the same constraint 0007_media's docstring calls out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009_messaging"
down_revision: Union[str, None] = "0008_user_full_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    # --- presence (§19) ---------------------------------------------------
    op.add_column(
        "users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- conversations ----------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("initiator_id", sa.Uuid(), nullable=False),
        # Canonical, sorted "these two people" key. UNIQUE so a simultaneous
        # first message from two devices cannot create two threads for one pair.
        # Nullable because a group conversation has no pair, and NULLs are
        # distinct in a unique index on both dialects.
        sa.Column("pair_key", sa.String(length=73), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.String(length=160), nullable=True),
        sa.Column("last_sender_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["initiator_id"], ["users.id"], ondelete="CASCADE"),
        # SET NULL: losing the sender must not delete the thread's history.
        sa.ForeignKeyConstraint(["last_sender_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("pair_key", name="uq_conversations_pair_key"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_public_id", "conversations", ["public_id"], unique=True)
    op.create_index(
        "ix_conversations_last_message_at", "conversations", ["last_message_at"]
    )

    # --- conversation_participants ----------------------------------------
    op.create_table(
        "conversation_participants",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "user_id"),
    )
    # The PK leads on conversation_id ("who is in this thread"). The inbox asks
    # the opposite question far more often, and the PK cannot serve it without a
    # scan — the same asymmetry 0006_follow_indexes fixed for user_follows.
    op.create_index(
        "ix_conversation_participants_user_conversation",
        "conversation_participants",
        ["user_id", "conversation_id"],
    )

    # --- messages ---------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column("shared_product_slug", sa.String(length=120), nullable=True),
        sa.Column("shared_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        # SET NULL on both attachments: a purged image or a deleted account must
        # leave the message standing as a record that something was sent.
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["shared_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_public_id", "messages", ["public_id"], unique=True)
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    # --- user_blocks (§22) ------------------------------------------------
    op.create_table(
        "user_blocks",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
    )
    # Every send checks BOTH directions, and the PK only answers "who have I
    # blocked". This index answers "who has blocked me".
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])

    # --- reports (§23) ----------------------------------------------------
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("reported_user_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reported_user_id"], ["users.id"], ondelete="CASCADE"),
        # SET NULL: deleting a conversation must not erase the report about it.
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_public_id", "reports", ["public_id"], unique=True)
    op.create_index(
        "ix_reports_reported_user_id", "reports", ["reported_user_id"]
    )


def downgrade() -> None:
    # Reverse creation order: reports and messages reference conversations, and
    # conversation_participants does too.
    op.drop_index("ix_reports_reported_user_id", table_name="reports")
    op.drop_index("ix_reports_public_id", table_name="reports")
    op.drop_table("reports")

    op.drop_index("ix_user_blocks_blocked_id", table_name="user_blocks")
    op.drop_table("user_blocks")

    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_public_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index(
        "ix_conversation_participants_user_conversation",
        table_name="conversation_participants",
    )
    op.drop_table("conversation_participants")

    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_index("ix_conversations_public_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_column("users", "last_seen_at")
