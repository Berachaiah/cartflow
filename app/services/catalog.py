"""
The product catalogue — placeholder data, real lookup rules.

This module exists because a product needs a URL. The catalogue used to live
inside shop.html as a Jinja `set`, which was fine while the only way to view a
product was a modal on that one page: the sheet read its facts off the tapped
card, so template-local data was enough. A dedicated `/product/{slug}` page
cannot work that way — the server has to resolve a slug it was handed in a URL,
and answer 404 for one it doesn't recognise. That decision belongs in Python,
next to the data it decides about.

So the shape is deliberate: `PRODUCTS` is a list of plain dicts keyed exactly
like the `GET /api/products` response doc 12 §26 describes, and every reader
(the Shop grid, the product page, the rails) goes through the accessors below.
When the `products` table lands:

  - `PRODUCTS` is deleted,
  - `list_products` / `get_product` / `related_products` grow an
    `AsyncSession` parameter and become queries,
  - their return shape does not change, so no template is touched.

`discount_percent` is here rather than in a Jinja filter for the same reason:
the grid badge, the product page chip and the cart's savings line must agree on
one rounding rule, and three templates rounding independently is how they stop
agreeing.
"""

import re

from app.core.exceptions import NotFoundError

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

# Field notes, since several of these drive behaviour rather than just text:
#   price / was    — `was` is the pre-discount price (doc 12 §12). None = no
#                    discount; the badge and the strike-through both follow it.
#   stock          — units available (§13): 0 → Out of stock and NOT addable to
#                    the cart, 1-5 → Low stock, more → In stock.
#   rating/reviews — §18 average and count. 0 reviews shows "No reviews yet"
#                    rather than a fake 0.0.
#   sold           — §11 "Most purchased" signal. pop — §11 "Recommended".
#   days           — how long ago it was listed, for §11 "Newest".
#   delivery       — §15 coverage. pickup — §16.
#
# Every image URL is already in use elsewhere in the app (home / discover), so
# none of them can 404 here.
PRODUCTS: list[dict] = [
    {
        "slug": "campus-essential-hoodie",
        "name": "Campus Essential Hoodie",
        "price": 18500,
        "was": 24000,
        "business": "RetroVibe Apparel",
        "handle": "retrovibe",
        "category": "Fashion",
        "rating": 4.8,
        "reviews": 214,
        "stock": 12,
        "sold": 480,
        "pop": 96,
        "days": 6,
        "tags": ["hoodie", "campuswear", "unisex"],
        "delivery": ["Bells University", "Ota", "Lagos"],
        "pickup": "Main Gate, Bells University",
        "desc": (
            "Heavyweight fleece hoodie cut for campus weather. Ships in three "
            "colourways with an embroidered CartFlow crest on the sleeve."
        ),
        "image": "https://images.unsplash.com/photo-1556821840-3a63f95609a7?q=80&w=600&auto=format&fit=crop",
        "alt": "Folded grey hoodie on a plain background",
    },
    {
        "slug": "airflux-midnight",
        "name": "AirFlux Midnight",
        "price": 42000,
        "was": None,
        "business": "SneakerLab",
        "handle": "sneakerlab",
        "category": "Fashion",
        "rating": 4.9,
        "reviews": 168,
        "stock": 4,
        "sold": 320,
        "pop": 94,
        "days": 2,
        "tags": ["sneakers", "shoes", "airflux"],
        "delivery": ["Covenant University", "Ota", "Lagos", "Nationwide"],
        "pickup": "Shop 14, Covenant Plaza",
        "desc": (
            "Low-profile trainer with a cushioned midsole. Runs true to size; "
            "half sizes available on request."
        ),
        "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?q=80&w=600&auto=format&fit=crop",
        "alt": "Dark sneaker photographed from the side",
    },
    {
        "slug": "power-bank-20000",
        "name": "Power Bank 20,000mAh",
        "price": 14500,
        "was": 19000,
        "business": "CampusTech Store",
        "handle": "campustech",
        "category": "Electronics",
        "rating": 4.6,
        "reviews": 96,
        "stock": 31,
        "sold": 655,
        "pop": 92,
        "days": 11,
        "tags": ["power bank", "charger", "usb-c"],
        "delivery": ["Bells University", "Ota", "Ogun State", "Lagos"],
        "pickup": "CampusTech, Faculty Road",
        "desc": (
            "Fast-charge power bank with two USB-C ports and a pass-through "
            "mode. Enough for four phone charges between wall sockets."
        ),
        "image": "https://images.unsplash.com/photo-1609091839311-d5365f9ff1c5?q=80&w=600&auto=format&fit=crop",
        "alt": "Black power bank with a charging cable",
    },
    {
        "slug": "ocean-breeze-perfume",
        "name": "Ocean Breeze Perfume",
        "price": 9800,
        "was": None,
        "business": "Luxe Fashion",
        "handle": "luxe",
        "category": "Beauty",
        "rating": 4.7,
        "reviews": 58,
        "stock": 18,
        "sold": 210,
        "pop": 86,
        "days": 20,
        "tags": ["perfume", "fragrance", "unisex"],
        "delivery": ["Babcock University", "Lagos", "Nationwide"],
        "pickup": "Luxe Studio, Ikeja",
        "desc": (
            "A clean citrus-and-salt fragrance that holds for a full lecture "
            "day. 50ml glass bottle."
        ),
        "image": "https://images.unsplash.com/photo-1595425970377-c9703cf48b6d?q=80&w=600&auto=format&fit=crop",
        "alt": "Perfume bottle on a marble surface",
    },
    {
        "slug": "jollof-rice-combo",
        "name": "Jollof Rice Combo",
        "price": 3200,
        "was": 4000,
        "business": "FoodHub Campus Kitchen",
        "handle": "foodhub",
        "category": "Food",
        "rating": 4.9,
        "reviews": 402,
        "stock": 25,
        "sold": 1840,
        "pop": 91,
        "days": 1,
        "tags": ["jollof", "lunch", "chicken"],
        "delivery": ["Bells University", "Ota"],
        "pickup": "FoodHub, Student Centre",
        "desc": (
            "Smoky party jollof with grilled chicken, plantain and coleslaw. "
            "Cooked to order between 11am and 8pm."
        ),
        "image": "https://images.unsplash.com/photo-1604329760661-e71dc83f8f26?q=80&w=600&auto=format&fit=crop",
        "alt": "Plate of jollof rice with chicken",
    },
    {
        "slug": "led-study-lamp",
        "name": "LED Study Lamp",
        "price": 7400,
        "was": None,
        "business": "CampusTech Store",
        "handle": "campustech",
        "category": "Electronics",
        "rating": 4.4,
        "reviews": 41,
        "stock": 0,
        "sold": 275,
        "pop": 78,
        "days": 34,
        "tags": ["lamp", "desk", "study"],
        "delivery": ["Bells University", "Ota", "Lagos"],
        "pickup": "CampusTech, Faculty Road",
        "desc": (
            "Clamp-on desk lamp with three colour temperatures and a USB port. "
            "Runs off a power bank during outages."
        ),
        "image": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?q=80&w=600&auto=format&fit=crop",
        "alt": "Lit desk lamp beside an open notebook",
    },
    {
        "slug": "canvas-tote-bag",
        "name": "Canvas Tote Bag",
        "price": 6500,
        "was": 8500,
        "business": "RetroVibe Apparel",
        "handle": "retrovibe",
        "category": "Accessories",
        "rating": 4.5,
        "reviews": 73,
        "stock": 3,
        "sold": 190,
        "pop": 74,
        "days": 4,
        "tags": ["tote", "bag", "canvas"],
        "delivery": ["Bells University", "Ota", "Lagos"],
        "pickup": "Main Gate, Bells University",
        "desc": (
            "Twelve-ounce canvas tote that swallows a laptop, two textbooks and "
            "a water bottle. Reinforced straps."
        ),
        "image": "https://images.unsplash.com/photo-1592286927505-1def25115558?q=80&w=600&auto=format&fit=crop",
        "alt": "Plain canvas tote bag hanging on a hook",
    },
    {
        "slug": "hardcover-notebook-set",
        "name": "Hardcover Notebook Set",
        "price": 4200,
        "was": None,
        "business": "Inkwell Stationery",
        "handle": "inkwell",
        "category": "Stationery",
        "rating": 4.8,
        "reviews": 34,
        "stock": 60,
        "sold": 145,
        "pop": 70,
        "days": 9,
        "tags": ["notebook", "a5", "dotted"],
        "delivery": ["Bells University", "Ota", "Ogun State"],
        "pickup": "Inkwell, Ota Market",
        "desc": (
            "Three A5 hardcovers — dotted, ruled and blank — with 120gsm paper "
            "that does not bleed through."
        ),
        "image": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?q=80&w=600&auto=format&fit=crop",
        "alt": "Notebooks stacked on a study desk",
    },
    {
        "slug": "everyday-wristwatch",
        "name": "Everyday Wristwatch",
        "price": 22000,
        "was": 31000,
        "business": "Luxe Fashion",
        "handle": "luxe",
        "category": "Accessories",
        "rating": 4.3,
        "reviews": 22,
        "stock": 7,
        "sold": 88,
        "pop": 68,
        "days": 15,
        "tags": ["watch", "steel", "gift"],
        "delivery": ["Lagos", "Nationwide"],
        "pickup": "Luxe Studio, Ikeja",
        "desc": (
            "Slim 38mm case on a mesh strap. Water resistant to 30m, which "
            "covers rain and a sink, not swimming."
        ),
        "image": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?q=80&w=600&auto=format&fit=crop",
        "alt": "Wristwatch with a steel mesh strap",
    },
    {
        "slug": "wireless-earbuds-pro",
        "name": "Wireless Earbuds Pro",
        "price": 26500,
        "was": 34000,
        "business": "CampusTech Store",
        "handle": "campustech",
        "category": "Electronics",
        "rating": 4.5,
        "reviews": 129,
        "stock": 9,
        "sold": 512,
        "pop": 88,
        "days": 3,
        "tags": ["earbuds", "bluetooth", "anc"],
        "delivery": ["Bells University", "Ota", "Lagos", "Nationwide"],
        "pickup": "CampusTech, Faculty Road",
        "desc": (
            "Active noise cancelling earbuds with a 28-hour case. Pairs with "
            "two devices at once, which lectures and calls both like."
        ),
        "image": "https://images.unsplash.com/photo-1600185365483-26d7a4cc7519?q=80&w=600&auto=format&fit=crop",
        "alt": "Wireless earbuds resting in their charging case",
    },
    {
        "slug": "matte-lip-set",
        "name": "Matte Lip Set",
        "price": 8900,
        "was": None,
        "business": "Glow Bar",
        "handle": "glowbar",
        "category": "Beauty",
        "rating": 0,
        "reviews": 0,
        "stock": 14,
        "sold": 0,
        "pop": 52,
        "days": 0,
        "tags": ["lipstick", "matte", "set"],
        "delivery": ["Bells University", "Ota", "Lagos"],
        "pickup": "Glow Bar, Ota",
        "desc": (
            "Four transfer-resistant shades in a travel case. New listing — no "
            "reviews yet."
        ),
        "image": "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?q=80&w=600&auto=format&fit=crop",
        "alt": "Row of lipsticks on a pale background",
    },
    {
        "slug": "oversized-campus-tee",
        "name": "Oversized Campus Tee",
        "price": 11500,
        "was": 15000,
        "business": "RetroVibe Apparel",
        "handle": "retrovibe",
        "category": "Fashion",
        "rating": 4.6,
        "reviews": 47,
        "stock": 21,
        "sold": 260,
        "pop": 66,
        "days": 27,
        "tags": ["tee", "tshirt", "oversized"],
        "delivery": ["Bells University", "Ota", "Lagos"],
        "pickup": "Main Gate, Bells University",
        "desc": (
            "Boxy 240gsm tee that keeps its shape through the wash. "
            "Screen-printed, not transferred, so the graphic outlasts the term."
        ),
        "image": "https://images.unsplash.com/photo-1620799140408-edc6dcb6d633?q=80&w=600&auto=format&fit=crop",
        "alt": "Model wearing an oversized black tee",
    },
]

PRODUCT_NOT_FOUND_MESSAGE = "That product doesn't exist."

# Same shape as the slugs above: lowercase words joined by single hyphens. The
# pattern runs BEFORE the lookup so a hand-crafted 10 KB path segment is
# rejected on sight rather than compared against every product in the list.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_MAX_LENGTH = 80

_BY_SLUG: dict[str, dict] = {p["slug"]: p for p in PRODUCTS}


def naira(amount) -> str:
    """`18500` → `₦18,500`. The one place that decides how a price reads.

    Registered as a Jinja global (app/routers/pages.py) and called by the
    `money()` macro, so a server-rendered price and a price the browser prints
    from the JSON index below cannot disagree: no kobo, thousands separated,
    symbol tight against the digits. Prices in the catalogue are whole naira, and
    ".00" on every one of them is noise.
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


def list_products() -> list[dict]:
    """The whole catalogue, in curation order.

    Returns the module list itself rather than a copy — templates only read it,
    and a copy per request would be 12 dicts of pure waste. If a caller ever
    needs to mutate, it copies.
    """
    return PRODUCTS


def get_product(slug: str) -> dict:
    """One product by slug, or raise NotFoundError.

    Raises rather than returning None so a page route and a future API endpoint
    reach the same answer for a bad slug without each remembering to check.
    """
    candidate = (slug or "").strip().lower()
    if len(candidate) > _SLUG_MAX_LENGTH or not _SLUG_PATTERN.match(candidate):
        raise NotFoundError(PRODUCT_NOT_FOUND_MESSAGE)

    product = _BY_SLUG.get(candidate)
    if product is None:
        raise NotFoundError(PRODUCT_NOT_FOUND_MESSAGE)
    return product


def related_products(product: dict, *, limit: int = 6) -> list[dict]:
    """Same category, this product excluded (doc 12 §21).

    Falls back to the most-sold products from other categories when a category
    holds only one item — "More like this" showing nothing is a dead end on the
    one page whose job is keeping a shopper moving.
    """
    same = [
        p
        for p in PRODUCTS
        if p["category"] == product["category"] and p["slug"] != product["slug"]
    ]
    if len(same) >= 2:
        return same[:limit]

    fill = sorted(
        (p for p in PRODUCTS if p["slug"] != product["slug"] and p not in same),
        key=lambda p: p["sold"],
        reverse=True,
    )
    return (same + fill)[:limit]


def browse_index() -> list[dict]:
    """The catalogue trimmed to what a browser needs to draw a product tile.

    Home's "Recently viewed" rail and Discover's client-side search both render
    product rows in JavaScript, and both used to carry their own copy of the
    names, prices and images — which is how "₦1.35M" on one screen and
    "₦1,350,000" on another end up in the same app. They now read this, and the
    price arrives already formatted by `naira` so no JS has to re-invent it.

    Deliberately NOT the whole dict: `desc`, `stock` and `delivery` are page
    concerns, and a leaner payload is a smaller page.
    """
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
        for p in PRODUCTS
    ]


def catalog_context() -> dict:
    """The keys every catalogue-rendering template expects.

    Kept as one call so the Shop, the product page, Home and Discover can't be
    given different category lists or sort orders by a route that forgot a key.
    `product_map` is what lets a template hold a slug and print a price: the feed
    tags a product by slug, and looking the facts up here means a tagged product
    and its own page can never quote different numbers.
    """
    return {
        "products": list_products(),
        "product_map": _BY_SLUG,
        "browse_index": browse_index(),
        "categories": CATEGORIES,
        "sort_options": SORT_OPTIONS,
        "coverage_areas": COVERAGE_AREAS,
    }
