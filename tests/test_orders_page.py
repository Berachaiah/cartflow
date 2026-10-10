"""
Render tests for /orders — the buyer's post-purchase page.

Doc 14 §25 names six tables (orders, order_items, order_status_history,
deliveries, disputes, refunds) and NONE of them exists, so the one thing these
tests really guard is honesty: the page must render the four §18 history
categories EMPTY and must never contain a specimen order. A fake order card
carries a business name, an amount and an escrow state — it reads as a claim
about the user's own money, which is worse than a fake metric. Hence the
`"₦" not in body` assertion: no currency figure has any business on this page
until there is a row behind it.

The other two rules:

  1. Signed out is a PAGE, not a redirect. /orders is bookmarkable, and the
     escrow/lifecycle explainers are exactly what someone deciding whether to
     trust the app wants to read.
  2. A seller's INCOMING orders live in the Business Hub (§6). Someone who owns
     a business gets a pointer at /dashboard#orders; someone who doesn't must not
     see it. The gate is the organization row, not `users.is_seller`.

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

from httpx import AsyncClient

PASSWORD = "password123"


async def _signup_and_login(client: AsyncClient, username: str, **extra) -> None:
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
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


# --- signed out ----------------------------------------------------------

async def test_orders_signed_out_prompts_login_and_still_explains(client: AsyncClient):
    """No cookie → 200 with a log-in prompt AND the explainers, never a 401 and
    never the tab set (there is no history to categorise for a visitor)."""
    r = await client.get("/orders")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Log in to see your orders" in body
    # The history tabs belong to a signed-in user only. Matched on the rendered
    # button attribute, not the bare `data-ord-tab` string — the delegated click
    # listener in the script block mentions the selector on every render.
    assert 'data-ord-tab="current"' not in body
    # The doc-14 rules render for everyone — that's what makes this page useful
    # with zero orders.
    assert "How an order works" in body
    assert "Auto-release after 72 hours" in body
    assert "This page hasn't been built yet" not in body   # no longer a stub


# --- signed in -----------------------------------------------------------

async def test_orders_signed_in_shows_four_empty_categories(client: AsyncClient):
    """Doc §18's four categories, all present and all honestly empty."""
    await _signup_and_login(client, "buyer")

    r = await client.get("/orders")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Log in to see your orders" not in body
    for key in ("current", "completed", "cancelled", "refunded"):
        assert f'data-ord-tab="{key}"' in body, f"missing tab: {key}"
        assert f'id="ordPanel-{key}"' in body, f"missing panel: {key}"
    # Empty states, not rows.
    assert "No orders in progress" in body
    assert "No completed orders yet" in body
    assert "buyer" in body            # identity in the chrome


async def test_orders_never_renders_a_fake_order(client: AsyncClient):
    """The honesty rule, as an assertion. No amount, no order number, no payment
    reference — there is no orders table, so any of those would be invented."""
    await _signup_and_login(client, "honest")

    body = (await client.get("/orders")).text
    assert "₦" not in body            # no money figure anywhere on the page
    assert "Order #" not in body
    assert "Payment reference" not in body


async def test_orders_reference_sheets_render(client: AsyncClient):
    """Both reference sheets ship in the HTML: on a phone they are the only route
    to the status list and the escrow explanation (the aside is xl-only)."""
    await _signup_and_login(client, "reader")

    body = (await client.get("/orders")).text
    assert 'id="statusSheet"' in body
    assert 'id="escrowSheet"' in body
    # doc §4 statuses, including the three exceptions
    for status in ("Pending payment", "Seller confirmed", "Ready for pickup", "Disputed"):
        assert status in body, f"missing status: {status}"
    # doc §17 escrow states
    for state in ("Held", "Released", "Refunded"):
        assert state in body, f"missing escrow state: {state}"
    # doc §10 — the surprising bit, stated before purchase rather than after
    assert "CartFlow does not assign couriers" in body


# --- seller cross-link (doc §6) ------------------------------------------

async def test_orders_points_a_seller_at_the_business_hub(client: AsyncClient):
    """A seller's incoming orders are the Hub's page, so /orders links there
    rather than silently showing them nothing."""
    await _signup_and_login(
        client, "sellerx", role="brand", business_name="Royal Fragrance", state="Lagos"
    )

    body = (await client.get("/orders")).text
    assert "/dashboard#orders" in body
    assert "Royal Fragrance" in body
    assert "Selling, not buying?" in body


async def test_orders_hides_hub_link_from_a_buyer(client: AsyncClient):
    """No business → no Hub pointer. The gate is the organization row."""
    await _signup_and_login(client, "justabuyer")

    body = (await client.get("/orders")).text
    assert "/dashboard#orders" not in body
    assert "Selling, not buying?" not in body
