"""price offers + pinned product

Revision ID: 0012_offers_deal
Revises: 0011_message_extras
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_offers_deal"
down_revision: Union[str, None] = "0011_message_extras"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("offer_price", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("offer_listed", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("offer_status", sa.String(20), nullable=True))

    op.create_table(
        "conversation_products",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("product_slug", sa.String(120), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=True),
        sa.Column("sold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="SET NULL"),
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE public."conversation_products" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("conversation_products")
    op.drop_column("messages", "offer_status")
    op.drop_column("messages", "offer_listed")
    op.drop_column("messages", "offer_price")
