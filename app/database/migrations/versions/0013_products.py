"""products

Revision ID: 0013_products
Revises: 0012_offers_deal
Create Date: 2026-11-23

The catalogue's first table. Until now every product surface read a curated list
in app/services/catalog.py; this is the schema behind the accessors that replaced
it. Whole naira in `price`, per the model's note.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_products"
down_revision: Union[str, None] = "0012_offers_deal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("was_price", sa.Integer(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sold_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("popularity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating", sa.Numeric(2, 1), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("delivery_areas", sa.JSON(), nullable=True),
        sa.Column("pickup_address", sa.String(500), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("image_alt", sa.String(300), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("slug"),
        sa.CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
        sa.CheckConstraint(
            "was_price IS NULL OR was_price >= 0", name="ck_products_was_price_non_negative"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_products_organization_id", "products", ["organization_id"])
    op.create_index("ix_products_slug", "products", ["slug"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_status", "products", ["status"])
    op.create_index("ix_products_category_status", "products", ["category", "status"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE public."products" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_products_category_status", table_name="products")
    op.drop_index("ix_products_status", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_slug", table_name="products")
    op.drop_index("ix_products_organization_id", table_name="products")
    op.drop_table("products")
