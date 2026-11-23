"""
The product catalogue — queries on one side, the template's dict shape on the other.

This module used to hold `PRODUCTS`, a curated list of twelve dicts that every
catalogue surface rendered. Its own docstring said what would happen when a
`products` table arrived: the list would be deleted, the accessors would grow a
session parameter, and their return shape would not change so that no template
moved. That is what happened in 0013_products.

What is still here, and should stay here:

`naira()` and `discount_percent()` are formatting RULES, not data. The grid badge,
the rail badge, the product page chip and the cart's savings line must round the
same way and print the same symbol, and four templates doing their own arithmetic
is how a product becomes -23% on one screen and -22% on another.

`CATEGORIES`, `SORT_OPTIONS` and `COVERAGE_AREAS` are configuration: they describe
what a seller may pick and what the Shop may filter by. They are not products and
still have no table (the doc marks admin-managed categories as future work), so
they remain declared here rather than being invented per page.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.product import ProductRepository

# Doc 12 §7 — administrators manage these; hardcoded until a
# `product_categories` table exists. "Services" is deliberately absent: the doc
# marks it future, and an empty category is a dead end.
CATEGORIES: list[dict] = [
    {"name": "All", "icon": "apps"},
    {"name": "Fashion", "icon": "apparel"},
    {"name": "Electronics", "icon": "devices"},
    {"name": "Beauty", "icon": "spa"},
    {"name": "Food", "icon": "restaurant"},
    {"name": "Accessories", "icon": "watch"},
    {"name": "Stationery", "icon": "edit"},
    {"name": "Books", "icon": "menu_book"},
    {"name": "Health", "icon": "medical_services"},
    {"name": "Sports", "icon": "sports_soccer"},
]

# Doc 12 §11 — sort options, in the doc's order. `key` is read by the Shop's JS
# comparators; changing a label here changes nothing else.
SORT_OPTIONS: list[dict] = [
    {"key": "recommended", "label": "Recommended"},
    {"key": "newest", "label": "Newest"},
    {"key": "price_asc", "label": "Price: Low → High"},
    {"key": "price_desc", "label": "Price: High → Low"},
    {"key": "rated", "label": "Best rated"},
    {"key": "purchased", "label": "Most purchased"},
    {"key": "discount", "label": "Biggest discount"},
]

# Doc 12 §15 — delivery coverage, as a business would configure it.
COVERAGE_AREAS: list[str] = [
    "Bells University",
    "Ota",
    "Ogun State",
    "Lagos",
    "Nationwide",
]

PRODUCT_NOT_FOUND_MESSAGE = "That product doesn't exist."

# Lowercase words joined by single hyphens. The pattern runs BEFORE the lookup so
# a hand-crafted 10 KB path segment is rejected on sight rather than sent to the
# database.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_MAX_LENGTH = 80


def naira(amount) -> str:
    """`18500` → `₦18,500`. The one place that decides how a price reads.

    Registered as a Jinja global (app/routers/pages.py) and called by the
    `money()` macro, so a server-rendered price and a price the browser prints
    from the JSON index below cannot disagree: no kobo, thousands separated,
    symbol tight against the digits.
    """
    try:
        return f"₦{int(amount):,}"
    except (TypeError, ValueError):
        return "₦0"


def discount_percent(product: dict) -> int:
    """Whole-percent saving, or 0 when there's no `was` price.

    One rounding rule for the whole app: the grid badge, the rail badge and the
    product page chip all call this, so a product can never be -23% in one place
    and -22% in another.
    """
    was = product.get("was") or 0
    price = product.get("price") or 0
    if not was or was <= price:
        return 0
    return round((was - price) / was * 100)


def _validate_slug(slug: str) -> str:
    candidate = (slug or "").strip().lower()
    if len(candidate) > _SLUG_MAX_LENGTH or not _SLUG_PATTERN.match(candidate):
        raise NotFoundError(PRODUCT_NOT_FOUND_MESSAGE)
    return candidate


async def list_products(
    db: AsyncSession, *, category: str | None = None, limit: int = 200
) -> list[dict]:
    """The live catalogue, in curation order (popularity, then newest)."""
    return await ProductRepository(db).catalog(category=category, limit=limit)


async def get_product(db: AsyncSession, slug: str) -> dict:
    """One product by slug, or raise NotFoundError.

    Raises rather than returning None so the page route, the offer service and a
    future API endpoint all reach the same answer for a bad slug without each
    remembering to check. The slug is shape-checked before the query, so an
    absurd path segment costs no database round trip.
    """
    product = await ProductRepository(db).catalog_one(_validate_slug(slug))
    if product is None:
        raise NotFoundError(PRODUCT_NOT_FOUND_MESSAGE)
    return product


async def related_products(
    db: AsyncSession, product: dict, *, limit: int = 6
) -> list[dict]:
    """Same category, this product excluded (doc 12 §21).

    Falls back to the most-sold products from other categories when a category
    holds only one item — "More like this" showing nothing is a dead end on the
    one page whose job is keeping a shopper moving.
    """
    repo = ProductRepository(db)
    same = await repo.same_category(
        category=product["category"], exclude_slug=product["slug"], limit=limit
    )
    if len(same) >= 2:
        return same[:limit]

    fill = await repo.most_sold(
        exclude_slugs=[product["slug"], *[p["slug"] for p in same]], limit=limit
    )
    return (same + fill)[:limit]


async def browse_index(db: AsyncSession, *, limit: int = 200) -> list[dict]:
    """The catalogue trimmed to what a browser needs to draw a product tile.

    Home's rails and Discover's client-side search both render product rows in
    JavaScript, and both used to carry their own copy of the names, prices and
    images — which is how "₦1.35M" on one screen and "₦1,350,000" on another end
    up in the same app. They read this, and the price arrives already formatted by
    `naira` so no JS has to re-invent it.

    Deliberately NOT the whole dict: `desc`, `stock` and `delivery` are page
    concerns, and a leaner payload is a smaller page.
    """
    products = await list_products(db, limit=limit)
    return [
        {
            "slug": p["slug"],
            "name": p["name"],
            "price": p["price"],
            "price_text": naira(p["price"]),
            "business": p["business"],
            "category": p["category"],
            "image": p["image"],
            "pop": p["pop"],
        }
        for p in products
    ]


async def catalog_context(db: AsyncSession) -> dict:
    """The keys every catalogue-rendering template expects.

    Kept as one call so the Shop, the product page, Home and Discover can't be
    given different category lists or sort orders by a route that forgot a key.
    `product_map` is what lets a template hold a slug and print a price: the feed
    tags a product by slug, and looking the facts up here means a tagged product
    and its own page can never quote different numbers.
    """
    products = await list_products(db)
    return {
        "products": products,
        "product_map": {p["slug"]: p for p in products},
        "browse_index": await browse_index(db),
        "categories": CATEGORIES,
        "sort_options": SORT_OPTIONS,
        "coverage_areas": COVERAGE_AREAS,
    }
