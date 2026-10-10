"""
Business Hub — page states and the two endpoints behind it.

Two things are being guarded, and they are quite different.

**The gate.** /dashboard renders one of three states, decided SERVER-SIDE:
signed out, signed in with no business, and seller. That matters because the
alternative — shipping the hub markup to everyone and hiding it with CSS — puts
a shop's controls in the HTML of someone who doesn't have a shop. And the gate is
the `organizations` row (`owner_user_id`), never `users.is_seller`: the flag is a
denormalized mirror, so a hub rendered off it could exist with no business behind
it. `PATCH /api/business/profile` follows the same rule, which is why "no
business" is a 404 there rather than a 403.

**The honesty rule.** Doc 16 §30 lists seven tables that don't exist, and §6
illustrates the dashboard with ₦48,200 of revenue. That figure must never render
— a seller reading their own hub has no way to tell an example from their real
takings. The only live number is the follower count, and it is asserted here
against a real follow.

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

from httpx import AsyncClient

PASSWORD = "password123"


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


async def _logout(client: AsyncClient) -> None:
    await client.post("/api/auth/logout")


async def _seller(client: AsyncClient, username: str, name: str, **extra) -> None:
    """A `brand` account: the signup itself creates the owned business, so this is
    the shortest path to the seller state."""
    await _signup(
        client, username, role="brand", business_name=name, state="Lagos", **extra
    )
    await _login(client, username)


# --- the three page states -----------------------------------------------

async def test_hub_signed_out_prompts_login_without_shipping_the_hub(
    client: AsyncClient,
):
    """Signed out is a page, not a redirect — and it must not contain the hub."""
    r = await client.get("/dashboard")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Business Hub" in body
    assert 'id="hubPanel-dashboard"' not in body
    assert 'data-hub-tab="finance"' not in body


async def test_hub_without_a_business_offers_the_front_door(client: AsyncClient):
    """A signed-in account with no shop gets doc 16 §3's Start-selling CTA, and
    still no hub."""
    await _signup(client, "nobiz")
    await _login(client, "nobiz")

    r = await client.get("/dashboard")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Start selling on CartFlow" in body
    assert 'id="sellForm"' in body          # POST /api/auth/business/upgrade
    assert 'id="hubPanel-dashboard"' not in body


async def test_hub_for_a_seller_renders_every_section(client: AsyncClient):
    """Doc 16 §4's eight sections, all present as panels, with the business
    identity in the header."""
    await _seller(client, "royal", "Royal Fragrance")

    r = await client.get("/dashboard")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Royal Fragrance" in body
    for key in (
        "dashboard",
        "products",
        "orders",
        "events",
        "analytics",
        "operations",
        "finance",
        "settings",
    ):
        assert f'id="hubPanel-{key}"' in body, f"missing panel: {key}"
        assert f'data-hub-tab="{key}"' in body, f"missing tab: {key}"
    # A seller can't create a second business, so the upgrade form is absent.
    assert 'id="sellForm"' not in body
    # The editable-for-real controls.
    assert 'id="pickupSheet"' in body
    assert 'id="bizSheet"' in body


async def test_hub_never_renders_the_example_revenue(client: AsyncClient):
    """Doc 16 §6 illustrates the dashboard with ₦48,200. A seller cannot tell an
    illustration from their own money, so it must not appear."""
    await _seller(client, "honestshop", "Honest Shop")

    body = (await client.get("/dashboard")).text
    assert "48,200" not in body
    assert "13,000" not in body


async def test_hub_follower_count_is_real(client: AsyncClient):
    """The one live number on the page. One real follow must show as 1 — if the
    metric were hardcoded this is the test that catches it."""
    await _seller(client, "shopowner", "Shop Owner Ltd")
    await _logout(client)

    await _signup(client, "fan")
    await _login(client, "fan")
    r = await client.post("/api/users/shopowner/follow")
    assert r.status_code == 200, r.text
    await _logout(client)

    await _login(client, "shopowner")
    body = (await client.get("/dashboard")).text
    # The metric macro renders the value in its own element, so this pins the
    # number rather than matching a stray "1" elsewhere in the page.
    assert 'leading-none">1</p>' in body


# --- GET /api/business/profile -------------------------------------------

async def test_get_business_profile_requires_a_session(client: AsyncClient):
    """A private row: no cookie is 401, never an anonymous read."""
    r = await client.get("/api/business/profile")
    assert r.status_code == 401, r.text


async def test_get_business_profile_404_without_a_business(client: AsyncClient):
    await _signup(client, "plainuser")
    await _login(client, "plainuser")

    r = await client.get("/api/business/profile")
    assert r.status_code == 404, r.text


async def test_get_business_profile_returns_the_owned_row(client: AsyncClient):
    await _seller(client, "owner1", "Owner One Stores")

    r = await client.get("/api/business/profile")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["official_name"] == "Owner One Stores"
    assert data["state"] == "Lagos"
    assert data["status"] == "unverified"
    # BusinessProfileOut is deliberately narrower than OrganizationOut.
    assert "owner_user_id" not in data


# --- PATCH /api/business/profile -----------------------------------------

async def test_patch_business_profile_requires_a_session(client: AsyncClient):
    r = await client.patch("/api/business/profile", json={"state": "Abuja"})
    assert r.status_code == 401, r.text


async def test_patch_business_profile_404_without_a_business(client: AsyncClient):
    """404, not 403: the row is looked up FROM the caller, so "not yours" and
    "doesn't exist" are the same condition."""
    await _signup(client, "notaseller")
    await _login(client, "notaseller")

    r = await client.patch("/api/business/profile", json={"state": "Abuja"})
    assert r.status_code == 404, r.text


async def test_patch_business_profile_edits_name_state_and_pickup(
    client: AsyncClient,
):
    await _seller(client, "editor", "Old Name Ltd")

    r = await client.patch(
        "/api/business/profile",
        json={
            "business_name": "New Name Ltd",
            "state": "Abuja",
            "pickup_address": "12 Allen Avenue, Ikeja",
        },
    )
    assert r.status_code == 200, r.text
    biz = r.json()["business"]
    assert biz["official_name"] == "New Name Ltd"
    assert biz["state"] == "Abuja"
    assert biz["pickup_address"] == "12 Allen Avenue, Ikeja"

    # Persisted, not just echoed.
    again = await client.get("/api/business/profile")
    assert again.json()["official_name"] == "New Name Ltd"

    # And rendered by the Hub.
    body = (await client.get("/dashboard")).text
    assert "New Name Ltd" in body
    assert "12 Allen Avenue, Ikeja" in body


async def test_patch_is_partial_and_leaves_omitted_fields_alone(client: AsyncClient):
    """`exclude_unset` is what lets the pickup sheet submit one field without
    resending the name."""
    await _seller(client, "partial", "Keep This Name")

    r = await client.patch(
        "/api/business/profile", json={"pickup_address": "Block C, Room 14"}
    )
    assert r.status_code == 200, r.text
    biz = r.json()["business"]
    assert biz["official_name"] == "Keep This Name"
    assert biz["state"] == "Lagos"
    assert biz["pickup_address"] == "Block C, Room 14"


async def test_explicit_null_clears_the_pickup_address(client: AsyncClient):
    """The one thing this endpoint fixes is the pickup-address dead-end, so
    clearing it has to work too: an emptied textarea sends null and the column
    goes back to NULL rather than storing "" or being ignored."""
    await _seller(client, "clearer", "Clearer Stores")
    await client.patch(
        "/api/business/profile", json={"pickup_address": "Somewhere temporary"}
    )

    r = await client.patch("/api/business/profile", json={"pickup_address": None})
    assert r.status_code == 200, r.text
    assert r.json()["business"]["pickup_address"] is None

    # A blank string is treated the same way (the validator normalizes it).
    await client.patch("/api/business/profile", json={"pickup_address": "  "})
    assert (await client.get("/api/business/profile")).json()["pickup_address"] is None


async def test_patch_rejects_an_empty_business_name(client: AsyncClient):
    """A shop with no name is not an edit, it's a mistake."""
    await _seller(client, "namer", "Real Name Ltd")

    for bad in ("", " ", "A"):
        r = await client.patch("/api/business/profile", json={"business_name": bad})
        assert r.status_code == 422, f"{bad!r} was accepted: {r.text}"

    assert (await client.get("/api/business/profile")).json()[
        "official_name"
    ] == "Real Name Ltd"


async def test_patch_cannot_self_verify_or_move_the_slug(client: AsyncClient):
    """Verification is an admin decision — a seller must not be able to promote
    their own shop out of 'unverified'. Unknown keys are ignored rather than
    rejected, so the request succeeds and the columns simply don't move."""
    await _seller(client, "sneaky", "Sneaky Stores")
    before = (await client.get("/api/business/profile")).json()

    r = await client.patch(
        "/api/business/profile",
        json={
            "state": "Oyo",
            "status": "verified",
            "slug": "premium-slug",
            "owner_user_id": "00000000-0000-4000-8000-000000000000",
        },
    )
    assert r.status_code == 200, r.text
    after = r.json()["business"]
    assert after["state"] == "Oyo"              # the legitimate edit applied
    assert after["status"] == "unverified"      # the illegitimate ones did not
    assert after["slug"] == before["slug"]
