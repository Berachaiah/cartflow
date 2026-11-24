"""
Render tests for the in-app HTML pages (home, shop, discover, and the shared
chrome).

The home feed was rebuilt to render real identity via `get_current_user_optional`
and a set of Jinja filters/macros (`caption_html`, `avatar_hue`, `avatar()`).
These tests guard the three things that can silently break:

  1. `/` must return 200 BOTH signed-out (no cookie → signed-out chrome, never a
     500) and signed-in (identity rendered).
  2. `_caption_html` must turn #hashtags / @mentions into links while escaping
     everything else — and must NOT mis-link the digits inside an escaped
     apostrophe entity (`&#39;`), which is why it runs on the raw caption.
  3. No inner route may serve `stub.html`. Every page in the sidebar is real
     now; a regression to the stub would still return 200, so it is asserted
     against by name.

The two pages with deep behaviour of their own live in their own files:
test_business_hub.py (/dashboard) and test_orders_page.py (/orders).

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

import re
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from markupsafe import Markup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.organization import Organization
from app.models.product import Product
from app.routers.pages import _caption_html


@pytest_asyncio.fixture
async def one_listing(engine):
    """A single row in the catalogue.

    The Shop grid is server-rendered from the `products` table now, so a render
    test that asserts on a card needs a card to exist. One listing is enough:
    the assertions below are about the page's controls and data attributes, not
    about how many sellers signed up.
    """
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        org = Organization(
            official_name="RetroVibe Apparel",
            short_name="RetroVibe Apparel",
            slug=f"retrovibe-{uuid.uuid4().hex[:8]}",
            country="Nigeria",
            state="Lagos",
            status="active",
        )
        session.add(org)
        await session.flush()
        session.add(
            Product(
                organization_id=org.id,
                slug="campus-essential-hoodie",
                name="Campus Essential Hoodie",
                category="Fashion",
                price=18500,
                was_price=24000,
                stock=12,
                description="Heavyweight fleece hoodie cut for campus weather.",
                image_url="https://example.com/hoodie.jpg",
                image_alt="Folded grey hoodie",
                popularity=96,
            )
        )
        await session.commit()
    return "campus-essential-hoodie"


async def _signup_and_login(
    client: AsyncClient, *, role: str, username: str, email: str, **extra
) -> None:
    """Create an account then log in, leaving the session cookie in the client's
    jar so the next GET renders as that user."""
    payload = {
        "role": role,
        "full_name": f"{username} Tester",
        "username": username,
        "email": email,
        "password": "password123",
        **extra,
    }
    r = await client.post("/api/auth/signup", json=payload)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": "password123"}
    )
    assert r.status_code == 200, r.text


# --- home render ---------------------------------------------------------

async def test_home_renders_signed_out(sample_feed, client: AsyncClient):
    """No session cookie → 200, branded chrome, and a log-in affordance rather
    than a 401 or a 500."""
    r = await client.get("/")
    assert r.status_code == 200, r.text
    body = r.text
    assert "CartFlow" in body
    assert "Log in" in body  # signed-out sidebar/right-rail affordance
    # Feed content rendered. The post is a real row now (`0014_posts`), so this
    # asserts the seeded author reached the page rather than reading a literal.
    assert "RetroVibe Apparel" in body


async def test_home_renders_signed_in(db, client: AsyncClient):
    """A logged-in individual sees their own identity in the chrome."""
    await _signup_and_login(
        client, role="individual", username="homeuser", email="homeuser@example.com"
    )
    r = await client.get("/")
    assert r.status_code == 200, r.text
    body = r.text
    assert "homeuser" in body  # @username / display name in the chrome
    # signed-in state must NOT show the logged-out prompt in the right rail
    assert "Welcome to CartFlow" not in body


async def test_inner_pages_render_signed_out(client: AsyncClient):
    """The three inner routes must render 200 with no session — and none of them
    is a stub any more. `stub.html` is what they all used to serve; if a route
    ever regresses to it, this is the test that says so.

    Their own behaviour is covered in depth elsewhere: /marketplace below,
    /dashboard in test_business_hub.py, /orders in test_orders_page.py.
    """
    for path in ("/marketplace", "/orders", "/dashboard"):
        r = await client.get(path)
        assert r.status_code == 200, f"{path}: {r.text}"
        assert "This page hasn't been built yet" not in r.text, f"{path} is a stub"


async def test_inner_pages_show_brand_in_mobile_bar(client: AsyncClient):
    """The default top bar must carry the CartFlow wordmark (mobile) rather than
    only the page title — the app reads "CartFlow" on every screen, and the
    bottom tab bar is what says which section you're in. The desktop-only title
    stays alongside it.

    The wordmark sits in a wrapper rather than carrying the responsive class
    itself, because the wrapper is what grows to centre it. Assert the wrapper's
    behaviour (mobile-only, centred) instead of one concatenated class string, so
    reordering utilities does not fail a test about where the brand appears.
    """
    r = await client.get("/marketplace")
    body = r.text
    assert 'CartFlow — home' in body                      # the wordmark's aria-label
    wrapper = re.search(
        r'<div class="([^"]*)">\s*<a href="/"[^>]*aria-label="CartFlow — home"', body
    )
    assert wrapper, "the mobile wordmark is not inside a wrapper element any more"
    tokens = wrapper.group(1).split()
    assert "lg:hidden" in tokens, "the wordmark shows at lg+, where the sidebar has it"
    # flex-1 claims the space the icon cluster leaves; justify-center centres the
    # link in it. Dead-centre on the viewport would sit under the icons.
    assert {"flex-1", "justify-center"} <= set(tokens), (
        f"the wordmark is no longer centred in the bar: {wrapper.group(1)!r}"
    )
    assert 'hidden lg:block font-display' in body         # title only on lg+
    assert ">Shop<" in body                               # Marketplace → Shop


# --- shop ----------------------------------------------------------------

async def test_shop_renders_catalogue_signed_out(one_listing, client: AsyncClient):
    """Shop is browsable with no session — doc 12 §3's search, category chips,
    grid and cart all render, and the grid is server-rendered from the products
    table rather than fetched (the cards ARE the source of truth the client-side
    sort/filter/cart read from, so they have to be in the HTML)."""
    r = await client.get("/marketplace")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'id="shopSearch"' in body        # universal product search
    assert 'id="productGrid"' in body       # the grid itself
    assert 'id="cartSheet"' in body         # cart lives in a sheet on this page
    assert 'id="sortSheet"' in body         # doc §11 sort
    assert 'id="filterSheet"' in body       # doc §10 filters
    assert 'id="gridEmpty"' in body         # a no-match filter set has an answer
    assert "Campus Essential Hoodie" in body
    assert 'data-slug="campus-essential-hoodie"' in body


async def test_shop_renders_signed_in(db, client: AsyncClient):
    await _signup_and_login(
        client, role="individual", username="shopper", email="shopper@example.com"
    )
    r = await client.get("/marketplace")
    assert r.status_code == 200, r.text
    assert "shopper" in r.text              # identity in the chrome


# --- discover ------------------------------------------------------------

async def test_discover_renders_signed_out(client: AsyncClient):
    """Discover is a real page now (not stub.html): the search affordance plus
    every explore section from doc 07 §4 must render with no session."""
    r = await client.get("/discover")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'id="discoverSearch"' in body           # universal search input
    assert 'id="discoverResults"' in body          # results region
    assert 'id="discoverExplore"' in body          # explore feed
    # doc 07 §4 sections, in order
    for heading in (
        "Trending searches",
        "Suggested students",
        "Suggested businesses",
        "Trending posts",
        "Trending products",
        "Upcoming events",
    ):
        assert heading in body, f"missing section: {heading}"
    # placeholder content actually rendered server-side
    assert "RetroVibe Apparel" in body
    assert "BUSA Annual Dinner" in body
    assert "This page hasn't been built yet" not in body   # no longer a stub


async def test_discover_renders_signed_in(db, client: AsyncClient):
    await _signup_and_login(
        client, role="individual", username="discoveruser", email="disc@example.com"
    )
    r = await client.get("/discover")
    assert r.status_code == 200, r.text
    assert "discoveruser" in r.text          # identity in the chrome


async def test_discover_prefills_q_param(client: AsyncClient):
    """`?q=` (how @mentions and the home search arrive) prefills the box so the
    client runs that search on load."""
    r = await client.get("/discover?q=Hoodies")
    assert r.status_code == 200, r.text
    assert 'value="Hoodies"' in r.text


async def test_discover_prefills_tag_param_with_sigil(client: AsyncClient):
    """`?tag=CampusWear` (how #hashtags arrive from a caption) must render as
    `#CampusWear` — the sigil is what makes the client rank hashtags first."""
    r = await client.get("/discover?tag=CampusWear")
    assert r.status_code == 200, r.text
    assert 'value="#CampusWear"' in r.text


async def test_discover_query_is_escaped_not_injected(client: AsyncClient):
    """The prefill lands in an HTML attribute, so a hostile ?q= must come back
    escaped — never as live markup."""
    r = await client.get('/discover?q=%22%3E%3Cscript%3Ealert(1)%3C/script%3E')
    assert r.status_code == 200, r.text
    body = r.text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body or "&amp;lt;script" in body


# --- shared chrome: the Create sheet -------------------------------------

async def test_create_button_opens_a_sheet_rather_than_nothing(client: AsyncClient):
    """Both `+` affordances used to be buttons with no id and no handler. They
    now carry the trigger attribute and the sheet ships with them."""
    body = (await client.get("/marketplace")).text
    assert 'id="createBtnDesktop"' in body          # sidebar (lg+)
    assert 'id="createBtnMobile"' in body           # centre of the tab bar
    assert body.count("data-cf-create-open") >= 2   # both wired to the same sheet
    assert 'id="createSheet"' in body


async def test_create_sheet_signed_out_offers_an_account(client: AsyncClient):
    """With no session there is nothing to create, so the sheet says so and
    points at log in / sign up — not at a composer."""
    body = (await client.get("/marketplace")).text
    assert "Log in to create anything" in body
    assert "Ready now" not in body                  # the signed-in group


async def test_create_sheet_offers_start_selling_to_a_non_seller(client: AsyncClient):
    """The one genuinely creative act a non-seller can perform today is creating
    a shop (POST /api/auth/business/upgrade), so that is the sheet's first row.
    Asserted on /marketplace because home renders its own "Start selling" link in
    the right rail — this has to be the sheet's."""
    await _signup_and_login(
        client, role="individual", username="maker", email="maker@example.com"
    )
    body = (await client.get("/marketplace")).text
    assert "Ready now" in body
    assert "Start selling" in body
    assert "Manage your shop" not in body           # they have no shop to manage
    assert "Edit your profile" in body
    # Deep-links straight into the editor sheet rather than dropping them on the
    # profile to hunt for the ⋯ button (profile.html reads the hash on load).
    assert "/@maker#edit" in body


async def test_create_sheet_offers_shop_management_to_a_seller(client: AsyncClient):
    """A seller can't create a second business, so the row changes rather than
    repeating an offer they've already taken."""
    await _signup_and_login(
        client,
        role="brand",
        username="sellermaker",
        email="sellermaker@example.com",
        business_name="Maker Studios",
        state="Lagos",
    )
    body = (await client.get("/marketplace")).text
    assert "Manage your shop" in body
    assert "Start selling" not in body


async def test_create_sheet_never_ships_a_composer(client: AsyncClient):
    """The sheet still has no composer, and no longer advertises gaps that closed.

    Rewritten when posts and products landed. It used to assert that four rows
    explained what each missing feature was waiting on — "needs posts + media",
    "needs products". Two of those statements became false the moment the tables
    existed, and a create button that tells you posts are unbuilt while the feed
    is full of them is the thing this test now prevents.

    The rule that survives is the honest one: no form whose submit would drop
    what it was given, and everything the sheet offers goes somewhere real.
    """
    body = (await client.get("/marketplace")).text
    for stale in (
        "needs posts + media",
        "needs products",
        "Coming soon",
    ):
        assert stale not in body, f"the create sheet still claims: {stale}"
    # The sheet is still there (it is the + button's target); what changed is that
    # it no longer carries a roadmap. Signed-out renders the log-in card instead
    # of the action rows, so only the sheet's presence is asserted here.
    assert 'id="createSheet"' in body


async def test_create_sheet_is_absent_from_bare_pages(client: AsyncClient):
    """`bare` pages (signup, login, password reset) render no chrome, so no `+`
    button and no sheet. Asserted on the ids rather than the trigger attribute:
    base's script always contains the selector string."""
    for path in ("/login", "/signup", "/forgot-password"):
        body = (await client.get(path)).text
        assert 'id="createSheet"' not in body, path
        assert 'id="createBtnMobile"' not in body, path
        assert 'id="createBtnDesktop"' not in body, path


async def test_home_start_selling_links_to_the_real_form(db, client: AsyncClient):
    """Regression: the right-rail CTA used to toast "Start selling — coming soon"
    while the endpoint behind it had shipped. It must link to the Hub's form."""
    await _signup_and_login(
        client, role="individual", username="railuser", email="rail@example.com"
    )
    body = (await client.get("/")).text
    assert "Start selling — coming soon" not in body
    assert '<a href="/dashboard" class="text-sm text-primary font-semibold shrink-0">Start selling</a>' in body


# --- caption filter ------------------------------------------------------
def test_caption_html_links_hashtags_and_mentions():
    out = _caption_html("New drop @retrovibe #CampusWear today")
    assert isinstance(out, Markup)
    assert '/discover?tag=CampusWear' in out
    # A mention points at the profile route, not a search. An unknown handle
    # lands on the rendered 404, which is the correct answer for a mention of an
    # account that doesn't exist.
    assert 'href="/@retrovibe"' in out
    assert '#CampusWear' in out
    assert '@retrovibe' in out


def test_caption_html_escapes_plain_text():
    """Angle brackets in the caption must be escaped, never rendered as HTML."""
    out = _caption_html("watch <script>alert(1)</script> here")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_caption_html_apostrophe_does_not_mislink():
    """Regression: escaping an apostrophe yields `&#39;`. If the tokenizer ran on
    the ESCAPED text it would see `#39` and wrongly link it. Running on the raw
    caption prevents that — the real #hashtag still links; `#39` never appears."""
    out = _caption_html("don't sleep on #Deals")
    assert "&#39;" in out                    # apostrophe was escaped
    assert "/discover?tag=Deals" in out      # the genuine hashtag linked
    assert "/discover?tag=39" not in out     # the entity digits did NOT


def test_caption_html_empty_is_blank_markup():
    assert _caption_html(None) == Markup("")
    assert _caption_html("") == Markup("")


def test_caption_html_preserves_newlines_as_br():
    out = _caption_html("line one\nline two")
    assert "<br>" in out
