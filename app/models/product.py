"""
Products — the catalogue in rows (docs/product/12-shop-and-products.md).

Until this table existed, the Shop, the product page, Home's rails, Discover's
search and the chat offer picker all read a curated list in
`app/services/catalog.py`. That module was written for exactly this moment: its
docstring said that when a `products` table landed, the list would be deleted and
the accessors would grow a session parameter, with the return shape unchanged so
no template moved. This is that table.

Three deliberate choices worth keeping:

*Whole naira in `price`.* Every price in this app is a whole naira figure and
`catalog.naira()` is the only thing that formats one. A payments integration will
want minor units (kobo) at the ledger boundary; doing that conversion in one
place when escrow lands is safer than half-converting here, where seventy
template call sites would silently start printing ₦18,500 for a ₦185.00 item.

`rating`/`review_count` are nullable/zero rather than invented.* There is no
`reviews` table, so a product with no reviews must say "No reviews yet" instead
of showing a made-up 4.8. The column exists so the moment reviews land the page
already knows where the number goes.

`sold_count` is NOT derived from orders.* There are no orders. It exists for the
"Most purchased" sort and for a seller moving stock in person; it is a number a
human maintains until `order_items` can compute it, and the Business Hub labels
it accordingly rather than claiming it is sales through CartFlow.
"""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import (
    Base,
    PublicIdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ProductStatus(str, enum.Enum):
    """`draft` is visible only to its owner; `archived` is a seller's own
    retirement. Deleting instead sets `deleted_at`, so a URL that was shared once
    can still answer 404 rather than a hard error."""

    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class Product(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """One listing. Owned by an organization, never by a user directly — the
    Business Hub gate is `organizations.owner_user_id`, and a product that pointed
    at a user would survive the seller losing the shop."""

    __tablename__ = "products"
    __table_args__ = (
        # A negative price or stock is a bug in a caller, not a business state.
        CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
        CheckConstraint("was_price IS NULL OR was_price >= 0", name="ck_products_was_price_non_negative"),
        # The Shop's category chips filter on one and hide the other.
        Index("ix_products_category_status", "category", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Globally unique, because the URL is /product/{slug} with no seller segment.
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    price: Mapped[int] = mapped_column(Integer, nullable=False)
    # The pre-discount price, when there is one. None means "no discount", which
    # is different from "discounted to zero" — the badge and the strike-through
    # both key off this being set.
    was_price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Doc 12 §11's "Recommended" ordering. A seller-editable-ish signal with no
    # ranking engine behind it yet (see doc 18, unbuilt) — the default keeps the
    # order stable rather than random.
    popularity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    delivery_areas: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pickup_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # A URL rather than a `media` FK: nothing uploads product photos yet, and the
    # sample listings carry Cloudinary/Unsplash URLs. When the upload path lands,
    # `image_media_id` joins this and the projection prefers the uploaded file.
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_alt: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProductStatus.ACTIVE.value, index=True
    )

    organization: Mapped["Organization"] = relationship(lazy="joined")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Product {self.slug}>"
