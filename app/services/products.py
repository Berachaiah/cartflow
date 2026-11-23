"""
Seller-side product operations: create, edit, retire, list.

Kept out of the router for the usual reason — these rules are testable without an
HTTP request, and the router's job is to resolve the caller's shop and translate
errors. Every function takes the ORGANIZATION the caller owns, never an
organization id from a payload, so there is no ownership check to forget: a
product is looked up through its shop.

The three rules that live here rather than in the schema:

*Slugs are generated, never supplied.* `/product/{slug}` is the public URL, so a
seller who names two products "Campus Tee" gets `campus-tee` and `campus-tee-2`
instead of the second silently overwriting the first, and a seller who types a
URL-shaped name cannot break the route.

*Archiving is a soft delete.* A shared link should 404 (`NotFoundError` from
`catalog.get_product`) rather than 500 on a missing row, and a seller who retires
a listing by mistake can be restored from the data without a backup.

*Editing a product re-reads it through the catalogue projection.* The API returns
what a shopper would see, not the ORM object, so the seller cannot be shown a
price the Shop would format differently.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.organization import Organization
from app.models.product import Product, ProductStatus
from app.repositories.product import ProductRepository, to_catalog_dict
from app.schemas.product import ProductCreateRequest, ProductUpdateRequest

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """`"Oversized Campus Tee"` → `"oversized-campus-tee"`.

    Matches the shape the route's pattern accepts (lowercase words, single
    hyphens), so anything this produces is addressable. Capped at 80 characters
    for the same reason `catalog._SLUG_MAX_LENGTH` exists — a slug is a URL path
    segment, not free text.
    """
    slug = _SLUG_STRIP.sub("-", (name or "").lower()).strip("-")
    return (slug or "listing")[:80].strip("-") or "listing"


async def _resolve_owned(db: AsyncSession, business: Organization, slug: str) -> Product:
    product = await ProductRepository(db).owned_by_slug(business.id, slug)
    if product is None:
        # Deliberately the same answer for "no such product" and "somebody
        # else's product": the difference is information about another seller's
        # inventory, and a 403 here would hand it over.
        raise NotFoundError("That product doesn't exist.")
    return product


async def create_product(
    db: AsyncSession, *, business: Organization, payload: ProductCreateRequest
) -> dict:
    repo = ProductRepository(db)
    slug = await repo.next_available_slug(slugify(payload.name))
    product = await repo.create(
        organization_id=business.id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        category=payload.category,
        price=payload.price,
        was_price=payload.was_price,
        stock=payload.stock,
        tags=payload.tags,
        delivery_areas=payload.delivery_areas,
        pickup_address=payload.pickup_address or business.pickup_address,
        image_url=payload.image_url,
        image_alt=payload.image_alt,
        status=payload.status,
    )
    await db.commit()
    await db.refresh(product)
    return to_catalog_dict(product)


async def update_product(
    db: AsyncSession,
    *,
    business: Organization,
    slug: str,
    payload: ProductUpdateRequest,
) -> dict:
    product = await _resolve_owned(db, business, slug)
    changes = payload.model_dump(exclude_unset=True)

    # `was_price` deliberately set to None must clear the discount, so it is read
    # from the dumped payload rather than defaulted. Validate the PAIR after the
    # merge, not the fields separately: lowering a price can make an existing
    # `was_price` invalid without either value being wrong on its own.
    was = changes.get("was_price", product.was_price)
    price = changes.get("price", product.price)
    if was is not None and was <= price:
        raise ValidationAppError(
            "The 'was' price has to be higher than the price.",
            fields={"was_price": "Must be higher than the price."},
        )

    for field, value in changes.items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return to_catalog_dict(product)


async def archive_product(db: AsyncSession, *, business: Organization, slug: str) -> None:
    product = await _resolve_owned(db, business, slug)
    await ProductRepository(db).soft_delete(product)
    await db.commit()


async def list_for_business(db: AsyncSession, *, business: Organization) -> list[dict]:
    """Every listing the shop owns, drafts included. The only catalogue view that
    includes drafts, and it is reachable only by the owner."""
    return await ProductRepository(db).by_owner(business.id)


async def stats_for_business(db: AsyncSession, *, business: Organization) -> dict:
    return await ProductRepository(db).stats_for_organization(business.id)


__all__ = [
    "archive_product",
    "create_product",
    "list_for_business",
    "slugify",
    "stats_for_business",
    "update_product",
    "ProductStatus",
]
