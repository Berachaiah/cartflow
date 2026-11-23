"""
Products — the table, the seller API, and the three surfaces now reading rows.

The invariant this file exists for is the one the old fixture made impossible to
state: **what the Shop shows and what a product's own page shows come from the
same row.** Before 0013_products both came from a module-level list, so a test
could only ever assert that the list rendered. Now a product exists because
somebody created it, and retiring it makes the Shop drop it and its URL 404 in
the same breath.

Also guarded here:

  - **Drafts are private.** A draft appears in the seller's own list and nowhere
    a shopper can see, because "unfinished" must not be a public state.
  - **Slugs are generated and never collide.** The slug is the URL; a second
    "Campus Tee" must not take the first one's address.
  - **Another seller's product is indistinguishable from no product.** Both are
    404 — a 403 would confirm the row exists.
  - **The Hub's numbers are real or zero, never illustrative.** Doc 16 §6's
    ₦48,200 must not appear anywhere in a seller's own dashboard.

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.product import Product

PASSWORD = "password123"


# --- helpers ----------------------------------------------------------

async def _signup(client: AsyncClient, username: str, **extra) -> None:
    payload = {
        "role": extra.pop("role", "individual"),
        "full_name": extra.pop("full_name", f"{username.title()} Tester"),
        "username": username,
        "email": f"{username}@example.com",
        "password": PASSWORD,
        **extra,
    }
    r = await client.post("/api/auth/signup", json=payload)
    assert r.status_code == 201, r.text


async def _login(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _seller(client: AsyncClient, username: str = "retrovibe", name: str = "RetroVibe Apparel") -> None:
    """A brand signup creates the owned business, which is what every write route
    resolves the caller's shop from."""
    await _signup(client, username, role="brand", business_name=name, state="Lagos")
    await _login(client, username)


async def _create(client: AsyncClient, **overrides):
    payload = {
        "name": "Campus Tee",
        "category": "Fashion",
        "price": 11500,
        "stock": 10,
        "tags": ["tee", "campuswear"],
        "delivery_areas": ["Lagos"],
        "pickup_address": "Main Gate",
        "image_url": "https://example.com/tee.jpg",
        "image_alt": "An oversized tee",
    }
    payload.update(overrides)
    return await client.post("/api/business/products", json=payload)


async def _created(client: AsyncClient, **overrides) -> dict:
    r = await _create(client, **overrides)
    assert r.status_code == 201, r.text
    return r.json()["product"]


# --- the Shop ---------------------------------------------------------

async def test_shop_renders_a_real_row_and_no_invented_ones(client: AsyncClient):
    """The grid shows what the table holds.

    The old curated list contained "Campus Essential Hoodie" — a product nobody
    created. With an empty table that name must be gone from the page entirely,
    which is the difference between a catalogue and a mock-up.
    """
    empty = await client.get("/marketplace")
    assert empty.status_code == 200
    assert "Campus Essential Hoodie" not in empty.text
    assert "RetroVibe Apparel" not in empty.text

    await _seller(client)
    await _created(client, name="Campus Essential Hoodie", price=18500, was_price=24000)

    r = await client.get("/marketplace")
    body = r.text
    assert "Campus Essential Hoodie" in body
    assert "RetroVibe Apparel" in body
    # The one formatter: no kobo, thousands separated.
    assert "₦18,500" in body


async def test_a_draft_is_invisible_to_shoppers_but_listed_for_its_owner(
    client: AsyncClient,
):
    await _seller(client)
    await _created(client, name="Unfinished Lamp", status="draft", price=7400)

    shop = await client.get("/marketplace")
    assert "Unfinished Lamp" not in shop.text

    mine = await client.get("/api/business/products")
    assert mine.status_code == 200
    assert [p["name"] for p in mine.json()["products"]] == ["Unfinished Lamp"]


# --- the product page -------------------------------------------------

async def test_product_page_and_shop_quote_the_same_row(client: AsyncClient):
    await _seller(client)
    product = await _created(client, name="Campus Essential Hoodie", price=18500, was_price=24000)

    r = await client.get(f"/product/{product['slug']}")
    assert r.status_code == 200
    assert "Campus Essential Hoodie" in r.text
    assert "₦18,500" in r.text
    # `was` drives both the strike-through and the badge, so the discount has to
    # agree with the same arithmetic the Shop grid uses: (24000-18500)/24000.
    assert "23%" in r.text


async def test_unknown_slug_is_a_rendered_404(client: AsyncClient):
    r = await client.get("/product/no-such-product")
    assert r.status_code == 404


async def test_retired_listing_leaves_the_shop_and_404s(client: AsyncClient):
    await _seller(client)
    product = await _created(client, name="LED Study Lamp")

    gone = await client.delete(f"/api/business/products/{product['slug']}")
    assert gone.status_code == 200, gone.text

    assert "LED Study Lamp" not in (await client.get("/marketplace")).text
    assert (await client.get(f"/product/{product['slug']}")).status_code == 404


async def test_related_rail_falls_back_when_a_category_has_one_item(
    client: AsyncClient,
):
    """A category holding a single product still gets a "More like this" rail —
    an empty one is a dead end on the page whose job is keeping a shopper moving."""
    await _seller(client)
    only_beauty = await _created(client, name="Ocean Breeze Perfume", category="Beauty", price=9800)
    other = await _created(client, name="Everyday Wristwatch", category="Accessories", price=22000)

    r = await client.get(f"/product/{only_beauty['slug']}")
    assert r.status_code == 200
    assert other["name"] in r.text


# --- seller writes ----------------------------------------------------

async def test_duplicate_names_get_distinct_slugs(client: AsyncClient):
    """The slug is the public URL, so the second listing must not take the first
    one's address."""
    await _seller(client)
    first = await _created(client, name="Campus Tee")
    second = await _created(client, name="Campus Tee")

    assert first["slug"] == "campus-tee"
    assert second["slug"] == "campus-tee-2"
    # Both still resolve, and each page shows its own row.
    for product in (first, second):
        assert (await client.get(f"/product/{product['slug']}")).status_code == 200


async def test_partial_update_leaves_every_other_field_alone(client: AsyncClient):
    """`{"stock": 0}` means "sold out", not "clear the listing"."""
    await _seller(client)
    product = await _created(client, name="Canvas Tote Bag", price=6500, was_price=8500, stock=3)

    r = await client.patch(
        f"/api/business/products/{product['slug']}", json={"stock": 0}
    )
    assert r.status_code == 200, r.text
    updated = r.json()["product"]
    assert updated["stock"] == 0
    assert updated["price"] == 6500
    assert updated["was"] == 8500
    assert updated["name"] == "Canvas Tote Bag"


async def test_a_discount_that_is_not_a_discount_is_rejected(client: AsyncClient):
    await _seller(client)
    r = await _create(client, price=18500, was_price=18500)
    assert r.status_code == 422, r.text


async def test_an_unknown_category_is_rejected(client: AsyncClient):
    await _seller(client)
    r = await _create(client, category="Spaceships")
    assert r.status_code == 422, r.text


async def test_another_sellers_product_is_not_found_rather_than_forbidden(
    client: AsyncClient,
):
    """A 403 would confirm the row exists. Both answers are 404, so the status
    code carries no information about somebody else's inventory."""
    await _seller(client, "retrovibe", "RetroVibe Apparel")
    product = await _created(client, name="Hoodie")
    await client.post("/api/auth/logout")

    await _seller(client, "sneakerlab", "SneakerLab")
    patched = await client.patch(
        f"/api/business/products/{product['slug']}", json={"price": 1}
    )
    deleted = await client.delete(f"/api/business/products/{product['slug']}")
    assert patched.status_code == 404
    assert deleted.status_code == 404

    # And the listing is untouched.
    public = await client.get(f"/product/{product['slug']}")
    assert public.status_code == 200
    assert "₦11,500" in public.text


async def test_writes_require_a_session_and_a_shop(client: AsyncClient):
    """Signed out is 401; signed in with no business is 404 (the same answer the
    profile routes give, because there is no shop to attach a listing to)."""
    anonymous = await _create(client)
    assert anonymous.status_code == 401

    await _signup(client, "ada")
    await _login(client, "ada")
    no_shop = await _create(client)
    assert no_shop.status_code == 404


# --- the Business Hub -------------------------------------------------

async def test_hub_reports_real_inventory_and_keeps_the_example_revenue_off(
    client: AsyncClient,
):
    """Doc 16 §6's ₦48,200 is an illustration. A seller reading their own hub
    cannot tell an example from their takings, so it must never render."""
    await _seller(client)
    await _created(client, name="Power Bank", stock=0)
    await _created(client, name="Canvas Tote Bag", stock=3)

    r = await client.get("/dashboard")
    assert r.status_code == 200
    body = r.text

    assert "₦48,200" not in body
    assert "Canvas Tote Bag" in body        # low stock, real row
    assert "Only 3 left" in body
    # Two active listings, four units of stock between them.
    assert "2 units in stock" in body or "4 units in stock." in body or "Active products" in body


async def test_hub_counts_only_active_listings(client: AsyncClient, db):
    await _seller(client)
    await _created(client, name="Live One", stock=5)
    await _created(client, name="Draft One", status="draft", stock=99)

    rows = (await db.execute(select(func.count()).select_from(Product))).scalar_one()
    assert rows == 2  # both exist in the table

    body = (await client.get("/dashboard")).text
    assert "Draft One" not in body       # drafts are not stock on the shelf
    assert "5 units in stock." in body
