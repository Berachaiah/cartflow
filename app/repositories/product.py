"""
Product catalogue queries, plus the one projection every catalogue surface uses.

The projection matters more than the queries. Shop, the product page, Home's
rails, Discover's client-side search and the chat offer picker all used to read
plain dicts out of `app/services/catalog.py`; they still do. `to_catalog_dict`
is the single place a row becomes those dicts, so a price printed on a card and
the same price on the product page cannot come from different arithmetic — which
is the failure the old module's docstring was guarding against, now that the
numbers come from the database.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.product import Product, ProductStatus
from app.models.user import User
from app.repositories.base import BaseRepository


def to_catalog_dict(product: Product, *, owner_username: str | None = None) -> dict:
    """A row as the dict shape the templates already expect.

    Keys are the ones the old curated list carried (`slug`, `name`, `price`,
    `was`, `business`, `handle`, `category`, `rating`, `reviews`, `stock`,
    `sold`, `pop`, `days`, `tags`, `delivery`, `pickup`, `desc`, `image`,
    `alt`). Renaming them here would mean touching twenty template call sites for
    no gain, so the column names stay modern and the projection keeps the
    contract.

    `days` is derived, not stored: "listed 6 days ago" is a function of the row's
    `created_at`, and a stored integer would be wrong by tomorrow.
    """
    org = product.organization
    created = product.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:  # SQLite returns naive datetimes
        created = created.replace(tzinfo=timezone.utc)

    business = (org.short_name or org.official_name) if org else "CartFlow seller"

    return {
        "slug": product.slug,
        "name": product.name,
        "price": int(product.price),
        "was": int(product.was_price) if product.was_price is not None else None,
        "business": business,
        # The seller's public handle for /@{handle}; falls back to the org slug so
        # a curated org with no owning user still links somewhere sensible.
        "handle": owner_username or (org.slug if org else ""),
        "category": product.category,
        # float() not str(): the template compares and formats this as a number,
        # and Decimal through a Jinja sum/badge is a type error waiting to happen.
        "rating": float(product.rating) if product.rating is not None else 0.0,
        "reviews": int(product.review_count or 0),
        "stock": int(product.stock),
        "sold": int(product.sold_count or 0),
        "pop": int(product.popularity or 0),
        "days": max(0, (datetime.now(timezone.utc) - created).days),
        "tags": list(product.tags or []),
        "delivery": list(product.delivery_areas or []),
        "pickup": product.pickup_address,
        "desc": product.description or "",
        "image": product.image_url,
        "alt": product.image_alt or product.name,
        # Additive, and only for the owner-facing views: the Business Hub's
        # listings panel is the one place a draft is visible (`by_owner`), and
        # without the status it would render a draft exactly like a live listing.
        "status": product.status,
    }


class ProductRepository(BaseRepository[Product]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Product)

    # --- catalogue (buyer-facing) -------------------------------------

    def _catalog_stmt(self):
        """Rows plus the seller's username, and nothing else.

        The username comes from the owning user of the organization, not from the
        product: a product has a shop, and a shop has an owner. An outer join
        because a curated organization (a university, a seeded demo shop) has no
        `owner_user_id` at all.
        """
        return (
            select(Product, User.username)
            .join(Organization, Organization.id == Product.organization_id)
            .outerjoin(User, User.id == Organization.owner_user_id)
            .where(Product.deleted_at.is_(None))
        )

    async def catalog(
        self,
        *,
        category: str | None = None,
        limit: int = 200,
        status: str = ProductStatus.ACTIVE.value,
    ) -> list[dict]:
        stmt = self._catalog_stmt().where(Product.status == status)
        if category and category.lower() not in ("", "all"):
            stmt = stmt.where(Product.category == category)
        stmt = stmt.order_by(Product.popularity.desc(), Product.created_at.desc()).limit(limit)
        rows = (await self.db.execute(stmt)).all()
        return [to_catalog_dict(p, owner_username=username) for p, username in rows]

    async def catalog_one(self, slug: str) -> dict | None:
        stmt = self._catalog_stmt().where(Product.slug == slug)
        row = (await self.db.execute(stmt)).first()
        if row is None:
            return None
        product, username = row
        return to_catalog_dict(product, owner_username=username)

    async def same_category(self, *, category: str, exclude_slug: str, limit: int = 6) -> list[dict]:
        stmt = (
            self._catalog_stmt()
            .where(
                Product.status == ProductStatus.ACTIVE.value,
                Product.category == category,
                Product.slug != exclude_slug,
            )
            .order_by(Product.popularity.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()
        return [to_catalog_dict(p, owner_username=u) for p, u in rows]

    async def most_sold(self, *, exclude_slugs: list[str], limit: int = 6) -> list[dict]:
        stmt = self._catalog_stmt().where(Product.status == ProductStatus.ACTIVE.value)
        if exclude_slugs:
            stmt = stmt.where(Product.slug.notin_(exclude_slugs))
        stmt = stmt.order_by(Product.sold_count.desc(), Product.popularity.desc()).limit(limit)
        rows = (await self.db.execute(stmt)).all()
        return [to_catalog_dict(p, owner_username=u) for p, u in rows]

    # --- seller-facing -------------------------------------------------

    async def by_owner(self, organization_id: uuid.UUID, *, limit: int = 100) -> list[dict]:
        """The seller's own listings, drafts included — this is the only listing
        view that includes them, and it is gated on ownership at the route."""
        stmt = (
            self._catalog_stmt()
            .where(Product.organization_id == organization_id)
            .order_by(Product.created_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()
        return [to_catalog_dict(p, owner_username=u) for p, u in rows]

    async def owned_by_slug(self, organization_id: uuid.UUID, slug: str) -> Product | None:
        """Resolve a product *through* the organization it must belong to.

        Same rule as the business profile routes: the row is looked up from the
        caller's shop, never from an id in the request, so there is no ownership
        check to forget. A slug that exists under somebody else's shop is simply
        not found here.
        """
        stmt = (
            self._base_query()
            .where(Product.organization_id == organization_id, Product.slug == slug)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def slug_taken(self, slug: str) -> bool:
        stmt = select(func.count()).select_from(Product).where(Product.slug == slug)
        return bool((await self.db.execute(stmt)).scalar_one())

    async def stats_for_organization(self, organization_id: uuid.UUID) -> dict:
        """The Business Hub's honest numbers (doc 16 §5).

        Only three of its ten metrics can be answered without orders, payments
        and events: how many listings are live, how much stock they add up to,
        and which are nearly gone. `sold` is the seller-maintained `sold_count`,
        labelled as such — the Hub must not present it as CartFlow sales.
        """
        active = Product.status == ProductStatus.ACTIVE.value
        not_deleted = Product.deleted_at.is_(None)

        totals = (
            await self.db.execute(
                select(
                    func.count(Product.id),
                    func.coalesce(func.sum(Product.stock), 0),
                    func.coalesce(func.sum(Product.sold_count), 0),
                ).where(Product.organization_id == organization_id, active, not_deleted)
            )
        ).one()
        count, stock, sold = int(totals[0]), int(totals[1]), int(totals[2])

        out_of_stock = (
            await self.db.execute(
                select(func.count(Product.id)).where(
                    Product.organization_id == organization_id,
                    active,
                    not_deleted,
                    Product.stock <= 0,
                )
            )
        ).scalar_one()

        low = (
            await self.db.execute(
                select(Product.name, Product.slug, Product.stock)
                .where(
                    Product.organization_id == organization_id,
                    active,
                    not_deleted,
                    Product.stock > 0,
                    Product.stock <= 5,
                )
                .order_by(Product.stock.asc())
                .limit(5)
            )
        ).all()

        return {
            "active": count,
            "stock": stock,
            "sold": sold,
            "out_of_stock": int(out_of_stock),
            "low_stock": [{"name": n, "slug": s, "stock": int(st)} for n, s, st in low],
        }

    async def next_available_slug(self, base: str) -> str:
        """`campus-tee`, then `campus-tee-2`, `campus-tee-3`…

        A slug is a URL people share, so a collision must not rename the existing
        product. Suffixing the newcomer keeps every published link working.
        """
        candidate = base or "listing"
        if not await self.slug_taken(candidate):
            return candidate
        n = 2
        while await self.slug_taken(f"{base}-{n}"):
            n += 1
        return f"{base}-{n}"
