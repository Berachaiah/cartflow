"""notifications

Revision ID: 0016_notifications
Revises: 0015_payments
Create Date: 2026-11-24

The activity store behind the bell. /notifications previously rendered the
follow graph because a follow edge was the only event the schema could prove;
money moving had no record of *having been announced*. A payment now writes one
row per recipient, and `emailed_at` records whether the courtesy email was
actually accepted, which is the first thing to check when a buyer says they
never heard about an order.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_notifications"
down_revision: Union[str, None] = "0015_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.String(300), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    # The inbox query: WHERE user_id = ? ORDER BY created_at DESC.
    op.create_index("ix_notifications_user_created_at", "notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_created_at", table_name="notifications")
    op.drop_index("ix_notifications_kind", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
