"""payments

Revision ID: 0015_payments
Revises: 0014_posts
Create Date: 2026-11-23

The first money table. Checkout used to end at a toast saying payments were not
live; with Flutterwave connected, each checkout attempt needs a row: a reference
the provider is asked to charge, the amount computed from the catalogue, and a
status that only moves on the provider's verified answer.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_payments"
down_revision: Union[str, None] = "0014_posts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False, server_default="flutterwave"),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("provider_reference", sa.String(64), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("items", sa.JSON(), nullable=True),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.Column("customer_name", sa.String(150), nullable=False),
        sa.Column("checkout_url", sa.String(512), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("reference"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_reference", "payments", ["reference"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_user_created_at", "payments", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_payments_user_created_at", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_reference", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")
