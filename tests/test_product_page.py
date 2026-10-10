"""
Render tests for /product/{slug} — the page a product preview became.

The Shop used to open a product in a sheet. It moved to its own route because a
listing carries a photo, a seller, a rating, a price pair, a description, delivery
coverage, a pickup point, a quantity control and a related rail, and none of that
fits in a phone-width modal. These tests guard what the move is worth:

  1. A KNOWN SLUG IS A PAGE, an unknown one is a rendered 404 at status 404 —
     not the JSON error envelope `register_exception_handlers` produces, because
     somebody who followed a stale product link is not an API client.
  2. THE SLUG IS NEVER TRUSTED. It arrives from the URL and is echoed on the 404,
     so a hostile one must come back escaped and length-capped.
  3. ONE PRICE FORMATTER. `catalog.naira` renders the figure on the product page,
     in the Shop grid, in the feed's product tags and in Discover's rail. The
     parity assertions below are what stop the same hoodie reading "₦18,500" on
     one screen and "18500" on another.
  4. THE PAGE IS SHAREABLE. That was the whole argument for the route, and the
     share URL must come from configuration rather than the Host header.

Also asserts that the two pages which grew a dependency on the catalogue — the
feed (product tags) and Discover (products are a searchable entity, doc 07 §5) —
still render with it and link into this route rather than previewing in a sheet.

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

import pytest
from httpx import AsyncClient

from app.services import catalog

# A product that exists in every fixture below. Read from the catalogue rather
# than typed as a literal so this file can't drift from the real slug set.
KNOWN = catalog.list_products()[0]


# --- the page itself -----------------------------------------------------

async def test_known_slug_renders_the_product(client: AsyncClient):
    r = await client.get(f"/product/{KNOWN['slug']}")
    assert r.status_code == 200, r.text
    body = r.text
    assert KNOWN["name"] in body
    assert KNOWN["business"] in body
    assert catalog.naira(KNOWN["price"]) in body       # the formatted figure
    assert 'id="pdAdd"' in body                        # add-to-cart control
    assert 'id="pdQty"' in body                        # quantity stepper
    assert "This page hasn't been built yet" not in body


async def test_every_catalogue_slug_resolves(client: AsyncClient):
    """Every slug the Shop grid, the feed's tags and Discover's rail link to must
    resolve — a 404 behind a link the app renders itself is a broken app, and the
    three surfaces all build their hrefs from this same list."""
    for product in catalog.list_products():
        r = await client.get(f"/product/{product['slug']}")
        assert r.status_code == 200, f"{product['slug']}: {r.status_code}"
        assert product["name"] in r.text


async def test_page_renders_signed_in(db, client: AsyncClient):
    """Browsable signed out (above) and signed in, with identity in the chrome."""
    await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Buyer Tester",
            "username": "pdbuyer",
            "email": "pdbuyer@example.com",
            "password": "password123",
        },
    )
    r = await client.post(
        "/api/auth/login", json={"identifier": "pdbuyer", "password": "password123"}
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/product/{KNOWN['slug']}")
    assert r.status_code == 200, r.text
    assert "pdbuyer" in r.text


async def test_the_dm_share_appears_only_for_someone_who_can_use_it(
    db, client: AsyncClient
):
    """Sharing a product into a chat is offered to a signed-in viewer and nobody
    else, and the phone control row counts its columns to match.

    Two things this defends. A "Send in a message" control for an anonymous
    visitor is a control that lies: /messages redirects them to /login, so the tap
    goes somewhere they didn't ask for. And the narrow row is a CSS grid whose
    column count moves with that control — two pills in a 3-column grid sit at
    two-thirds width with a hole where the third belongs, which is the kind of
    thing only a real render catches.

    The href carries the slug and sends nothing. That rule is asserted where it
    lives (tests/test_inboxes.py); here we only check the slug is the right one,
    because a share pointing at the wrong product is worse than no share.
    """
    path = f"/product/{KNOWN['slug']}"
    share_href = f'href="/messages?share={KNOWN["slug"]}"'

    anon = await client.get(path)
    assert anon.status_code == 200, anon.text
    assert share_href not in anon.text
    assert "Send in a message" not in anon.text
    assert "grid-cols-2 gap-2 mt-2.5 sm:hidden" in anon.text

    await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Sharer Tester",
            "username": "pdsharer",
            "email": "pdsharer@example.com",
            "password": "password123",
        },
    )
    r = await client.post(
        "/api/auth/login", json={"identifier": "pdsharer", "password": "password123"}
    )
    assert r.status_code == 200, r.text

    signed_in = await client.get(path)
    assert signed_in.status_code == 200, signed_in.text
    # Twice: the wide pill row beside the photo and the phone's control grid.
    assert signed_in.text.count(share_href) == 2
    assert "Send in a message" in signed_in.text
    assert "grid-cols-3 gap-2 mt-2.5 sm:hidden" in signed_in.text


async def test_related_rail_never_shows_the_product_itself(client: AsyncClient):
    """"More like this" exists to keep a shopper moving, so it must not offer the
    page they are already on."""
    r = await client.get(f"/product/{KNOWN['slug']}")
    assert r.status_code == 200, r.text
    # The page links to its own slug exactly once (the share/canonical use is a
    # JSON string, not an href), so a second href to it would be the rail.
    assert r.text.count(f'href="/product/{KNOWN["slug"]}"') == 0


async def test_share_url_is_absolute_and_not_from_the_host_header(
    client: AsyncClient,
):
    """The share button copies this string. Built from APP_BASE_URL rather than
    request.base_url — the latter is the Host header, so a spoofed one would end
    up inside a link the user hands to someone else.

    The negative below is deliberately narrow. Starlette's `url_for` returns an
    absolute URL assembled from the Host header, so every `<img src>` and
    `<script src>` on the page legitimately carries the spoofed host under this
    request; asserting the host is absent from the whole body would fail on the
    static assets while proving nothing about the share string. What must hold is
    that no *product link* is host-derived."""
    from app.core.config import get_settings

    base = get_settings().APP_BASE_URL.rstrip("/")
    r = await client.get(
        f"/product/{KNOWN['slug']}", headers={"Host": "evil.example"}
    )
    assert r.status_code == 200, r.text
    assert f"{base}/product/{KNOWN['slug']}" in r.text
    assert "evil.example/product/" not in r.text


# --- the 404 -------------------------------------------------------------

async def test_unknown_slug_is_a_rendered_404(client: AsyncClient):
    r = await client.get("/product/no-such-product")
    assert r.status_code == 404
    body = r.text
    assert "This product isn't available" in body
    assert "no-such-product" in body                   # echoed back
    assert '"error"' not in body                        # not the JSON envelope
    assert 'href="/marketplace"' in body                # a way forward


async def test_404_offers_real_alternatives(client: AsyncClient):
    """A dead end is the failure mode here: the page carries live catalogue rows
    so a stale link still lands somewhere useful."""
    r = await client.get("/product/no-such-product")
    assert r.status_code == 404
    assert KNOWN["name"] in r.text


async def test_hostile_slug_is_escaped_not_injected(client: AsyncClient):
    """The slug is echoed into the page, so a crafted one must come back as text.

    The payload has to be a single path segment: `/product/{slug}` matches one
    segment, so a `%2F`-free `</script>` (which decodes to a literal `/`) never
    reaches this route at all — it 404s in the router before the template runs,
    which tests the wrong thing. An `<img onerror>` is the same class of attack
    with no slash in it."""
    r = await client.get("/product/%3Cimg%20src=x%20onerror=alert(1)%3E")
    assert r.status_code == 404
    body = r.text
    assert "<img src=x onerror=alert(1)>" not in body
    assert "&lt;img" in body


async def test_absurdly_long_slug_is_capped(client: AsyncClient):
    """A 4 KB slug must not become a 4 KB paragraph. The route caps it at 60."""
    r = await client.get("/product/" + ("a" * 4000))
    assert r.status_code == 404
    assert "a" * 61 not in r.text


# --- price parity across the surfaces ------------------------------------

@pytest.mark.parametrize("path", ["/", "/discover", "/marketplace"])
async def test_price_reads_the_same_everywhere(client: AsyncClient, path: str):
    """One formatter, four surfaces. Every page that prints this product's price
    prints the string `catalog.naira` produces — no page re-implements grouping,
    and none of them prints a bare integer."""
    r = await client.get(path)
    assert r.status_code == 200, r.text
    assert catalog.naira(KNOWN["price"]) in r.text


async def test_feed_and_discover_link_into_the_product_route(client: AsyncClient):
    """Both pages used to open a product in a modal. They now link, which is the
    reason this route exists — asserted so a regression to a preview sheet is a
    failing test rather than a design someone re-litigates."""
    for path in ("/", "/discover"):
        body = (await client.get(path)).text
        assert "/product/" in body, f"{path} links to no product page"

    # Discover's own product tiles: a link, and no leftover preview payload.
    body = (await client.get("/discover")).text
    assert f'href="/product/{KNOWN["slug"]}"' in body
    assert '"action": "cart"' not in body
    assert 'id="peekPrice"' not in body
