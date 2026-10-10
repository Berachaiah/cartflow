"""
Render tests for /@username — the first page wired to real backend data.

The route is the only one in the app that has to answer a NotFoundError with
HTML: register_exception_handlers turns every AppException into the JSON error
envelope, which is right for /api/* and wrong for someone who tapped an
@mention. So the 404 path is tested as carefully as the 200 path.

The three rules these guard, none of which are visible from the template alone:

  1. Liked / Saved are PRIVATE. They must be absent from a visitor's HTML, not
     hidden with CSS — gating server-side is the only version that holds.
  2. A profile page must never contain the owner's email address. It renders a
     full `User` row, so this is one careless `{{ profile_user.email }}` away.
  3. Unknown, suspended and soft-deleted handles are indistinguishable: all
     three render the same 404, so no response confirms a hidden account.

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

import re
import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import AccountStatus, User

PASSWORD = "password123"
UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")


async def _seed_school(db: AsyncSession, official_name: str, short_name: str) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        organization_type_id=UNIVERSITY_TYPE_ID,
        official_name=official_name,
        short_name=short_name,
        slug=short_name.lower(),
        country="Nigeria",
        state="Lagos",
        status="active",
    )
    db.add(org)
    await db.commit()
    return org


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


# --- the 200 path --------------------------------------------------------

async def test_profile_renders_signed_out(client: AsyncClient):
    """A profile is public: no cookie must give a real page, not a 401."""
    await _signup(client, "ada", full_name="Ada Lovelace")

    r = await client.get("/@ada")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Ada Lovelace" in body
    assert "@ada" in body
    # Following is a write, so a signed-out visitor is told before the tap.
    assert "Log in to follow" in body


async def test_own_profile_shows_owner_tools(client: AsyncClient):
    await _signup(client, "ada", full_name="Ada Lovelace")
    await _login(client, "ada")

    r = await client.get("/@ada")
    assert r.status_code == 200, r.text
    body = r.text
    assert "Edit profile" in body
    assert 'id="editForm"' in body
    # The only log-out affordance in the whole app lives in this sheet.
    assert 'id="logoutBtn"' in body
    # Starting to sell moved to /settings, so the profile links there instead of
    # carrying its own upgrade form.
    assert 'id="sellForm"' not in body
    assert 'href="/settings"' in body
    # Owners get the photo control; visitors don't.
    assert 'data-open-sheet="photoSheet"' in body
    # Never a follow button on your own profile.
    assert 'id="followBtn"' not in body


async def test_visitor_profile_shows_follow_and_hides_owner_tools(client: AsyncClient):
    await _signup(client, "ada", full_name="Ada Lovelace")
    await _signup(client, "grace", full_name="Grace Hopper")
    await _login(client, "grace")

    r = await client.get("/@ada")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'id="followBtn"' in body
    assert 'id="editForm"' not in body
    assert 'id="sellForm"' not in body
    assert 'id="logoutBtn"' not in body
    assert 'data-open-sheet="photoSheet"' not in body


async def test_private_tabs_are_absent_for_a_visitor(client: AsyncClient):
    """Liked and Saved are owner-only (doc 08 §6). Gated server-side, so they
    must not appear in a visitor's markup at all — hiding them client-side would
    still ship the labels."""
    await _signup(client, "ada")
    await _signup(client, "grace")
    await _login(client, "grace")

    visitor_view = (await client.get("/@ada")).text
    assert 'data-tab="liked"' not in visitor_view
    assert 'data-tab="saved"' not in visitor_view

    await _login(client, "ada")
    own_view = (await client.get("/@ada")).text
    assert 'data-tab="liked"' in own_view
    assert 'data-tab="saved"' in own_view


async def test_business_profile_gets_the_seller_tab_set(client: AsyncClient):
    """`brand` is a standalone business: the owned org IS organization_id, so the
    page shows the storefront name and no school."""
    await _signup(
        client,
        "brandco",
        role="brand",
        full_name="Brand Co Owner",
        business_name="Brand Co",
        state="Lagos",
    )

    r = await client.get("/@brandco")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'data-tab="products"' in body
    assert 'data-tab="events"' in body
    assert 'data-tab="reviews"' in body
    assert "Brand Co" in body
    assert "Seller" in body


async def test_student_seller_shows_storefront_and_school_separately(
    db, client: AsyncClient
):
    """A student_business keeps the school as organization_id AND owns a business
    org. Both affiliations must render, once each — the template compares the two
    org ids so the shared row of a `brand` account isn't printed twice."""
    school = await _seed_school(db, "University of Lagos", "UNILAG")
    await _signup(
        client,
        "dualhat",
        role="student_business",
        full_name="Dual Hat",
        organization_id=str(school.id),
        business_name="Hat Depot",
        state="Lagos",
    )

    body = (await client.get("/@dualhat")).text
    assert "Hat Depot" in body
    assert "UNILAG" in body
    assert body.count("Hat Depot") == body.count("UNILAG")   # neither doubled
    assert 'data-tab="products"' in body                     # sells → seller tabs


async def test_customer_profile_has_no_seller_tabs_and_no_post_count(client: AsyncClient):
    """Posting is seller-gated, so a customer's profile shows neither a Posts tab
    NOR a Posts stat — a hardcoded "0 Posts" on someone who can't post is noise.
    Their stat row is followers · following only."""
    await _signup(client, "ada")
    body = (await client.get("/@ada")).text
    assert 'data-tab="products"' not in body
    assert 'data-tab="reviews"' not in body
    assert 'data-tab="posts"' not in body
    assert ">posts<" not in body          # the inline stat label
    assert ">followers<" in body
    assert ">following<" in body


async def test_seller_profile_keeps_posts_tab_and_count(client: AsyncClient):
    await _signup(
        client,
        "shop",
        role="brand",
        full_name="Shop Owner",
        business_name="Hat Depot",
        state="Lagos",
    )
    body = (await client.get("/@shop")).text
    assert 'data-tab="posts"' in body     # the tab
    assert ">posts<" in body              # and the inline stat label


async def test_handle_is_the_primary_identity_line(client: AsyncClient):
    """display_name isn't unique; the handle is. The @handle is the heading and
    the display name is the secondary line under it."""
    await _signup(client, "ada", full_name="Ada Lovelace")
    body = (await client.get("/@ada")).text
    assert 'id="profileHandle"' in body
    assert "@ada" in body
    assert body.index('id="profileHandle"') < body.index('id="profileName"')


async def test_profile_renders_real_follower_counts(client: AsyncClient):
    """The counts come from user_follows, not from a placeholder — following
    over the API must change what the page renders.

    Matched on the id and the number rather than the full class string, so a
    restyle of the stat row doesn't fail a test about the follow graph.
    """
    await _signup(client, "ada")
    await _signup(client, "grace")
    await _login(client, "grace")

    count_re = re.compile(r'id="followerCount"[^>]*>([\d,]+)<')

    before = (await client.get("/@ada")).text
    assert count_re.search(before).group(1) == "0"

    r = await client.post("/api/users/ada/follow")
    assert r.status_code == 200, r.text

    after = (await client.get("/@ada")).text
    assert count_re.search(after).group(1) == "1"
    # And the visitor's own button now renders in the Following state.
    assert 'data-following="true"' in after


async def test_profile_never_renders_an_email_address(client: AsyncClient):
    """The route hands the template a whole User row, so this is one careless
    {{ profile_user.email }} away at any time."""
    await _signup(client, "ada")
    await _signup(client, "grace")
    await _login(client, "grace")

    body = (await client.get("/@ada")).text
    assert "ada@example.com" not in body


async def test_bio_is_rendered_through_the_caption_filter(client: AsyncClient):
    """A bio gets tappable #hashtags and @mentions like a caption — and anything
    else in it must come back escaped, never as live markup."""
    await _signup(client, "ada")
    await _login(client, "ada")
    r = await client.patch(
        "/api/users/me", json={"bio": "selling #CampusWear <script>alert(1)</script>"}
    )
    assert r.status_code == 200, r.text

    body = (await client.get("/@ada")).text
    assert "/discover?tag=CampusWear" in body
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


# --- canonicalization ----------------------------------------------------

async def test_mixed_case_handle_redirects_to_canonical_casing(client: AsyncClient):
    """Handles match case-insensitively but store the casing the user typed, so
    one profile has one URL and shared links converge."""
    await _signup(client, "AdaL")

    r = await client.get("/@adal")
    # 302, not 301: handles are editable, and a permanent redirect cached in a
    # browser could outlive the name it points at.
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/@AdaL"

    # The canonical URL itself does not redirect (no loop).
    r = await client.get("/@AdaL")
    assert r.status_code == 200, r.text


# --- the 404 path --------------------------------------------------------

async def test_unknown_handle_renders_an_html_404(client: AsyncClient):
    r = await client.get("/@nobodyhere")
    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    # A page, not the API's JSON envelope.
    assert "This profile isn't available" in r.text
    assert "@nobodyhere" in r.text


async def test_hidden_accounts_are_indistinguishable_from_unknown_ones(
    db, client: AsyncClient
):
    """Suspended and soft-deleted handles must 404 exactly like handles that
    never existed — otherwise the status code confirms the account exists."""
    await _signup(client, "banned")
    await _signup(client, "erased")

    rows = (
        await db.execute(
            select(User).where(User.username_normalized.in_(["banned", "erased"]))
        )
    ).scalars().all()
    for row in rows:
        if row.username_normalized == "banned":
            row.account_status = AccountStatus.SUSPENDED
        else:
            row.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    for handle in ("banned", "erased", "nobodyhere"):
        r = await client.get(f"/@{handle}")
        assert r.status_code == 404, f"{handle}: {r.status_code}"
        assert "This profile isn't available" in r.text


async def test_malformed_handle_404s_without_touching_the_database(
    client: AsyncClient,
):
    """An oversized or illegal path segment is rejected on the username pattern
    before any query runs."""
    for bad in ("ab", "x" * 300, "has%20space"):
        r = await client.get(f"/@{bad}")
        assert r.status_code == 404, f"{bad}: {r.status_code}"


# --- chrome --------------------------------------------------------------

async def test_chrome_links_to_your_own_profile(client: AsyncClient):
    """base.html spends the old dead Settings slot on Profile, in both the
    sidebar and the mobile tab bar, so /@handle is always one tap away."""
    await _signup(client, "ada")
    await _login(client, "ada")

    body = (await client.get("/")).text
    assert body.count('href="/@ada"') >= 2
    assert ">Profile<" in body


async def test_signed_out_chrome_points_profile_at_login(client: AsyncClient):
    body = (await client.get("/")).text
    assert ">Profile<" in body
    assert "/@None" not in body
