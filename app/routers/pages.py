import re

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user_optional
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core import timeutils
from app.database.session import get_db
from app.models.report import REPORT_REASON_LABELS, REPORT_REASONS
from app.models.user import User
from app.repositories.organization import OrganizationRepository
from app.services import avatar as avatar_service
from app.services import catalog
from app.services import follow as follow_service
from app.services import messaging as messaging_service
from app.services import payments as payments_service
from app.services import posts as posts_service
from app.services import products as products_service
from app.services import google_oauth

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def _avatar_hue(seed: str | None) -> int:
    """Deterministic 0-359 hue from a seed (username), so a given account always
    gets the same colour wash behind its profile header. Plain rolling hash —
    stable across processes, unlike hash() which is salted per-run.

    (This used to colour the avatar itself, back when an account with no photo
    got initials on a coloured tile. The default is now a neutral silhouette —
    partials/avatar.html — and the hue survives only as the profile cover.)"""
    h = 0
    for ch in seed or "":
        h = (h * 31 + ord(ch)) % 360
    return h


# Matches a #hashtag or @mention that starts on a word boundary. Runs on the
# RAW caption (before HTML-escaping) so it can never collide with entities like
# &#39; that escaping would introduce.
_CAPTION_TOKEN_RE = re.compile(r"(?<!\w)([#@])(\w{1,60})")


def _caption_html(text: str | None) -> Markup:
    """Render a feed caption the way the product spec describes it (doc 06 §8-12):
    plain text with inline, tappable #hashtags and @mentions, and line breaks
    preserved. Everything between tokens is HTML-escaped, so a caption is safe to
    mark |safe in the template. Hashtags point at /discover?tag=; mentions point
    at the profile route /@handle. A mention of an account that doesn't exist
    lands on the friendly 404 page, which is the correct answer — better than
    silently routing every mention to a search. Emoji are left as literal
    Unicode and swapped to Twemoji images client-side."""
    if not text:
        return Markup("")
    out: list[str] = []
    pos = 0
    for m in _CAPTION_TOKEN_RE.finditer(text):
        out.append(str(escape(text[pos:m.start()])))
        sigil, word = m.group(1), escape(m.group(2))
        if sigil == "#":
            out.append(
                f'<a href="/discover?tag={word}" class="text-primary hover:underline">#{word}</a>'
            )
        else:
            out.append(
                f'<a href="/@{word}" class="text-primary hover:underline">@{word}</a>'
            )
        pos = m.end()
    out.append(str(escape(text[pos:])))
    return Markup("".join(out).replace("\n", "<br>"))


templates.env.filters["avatar_hue"] = _avatar_hue
templates.env.filters["caption_html"] = _caption_html

# Global, not a filter: it takes a User and a size name, and building a CDN URL
# is not a "transform this value" operation. Templates call
# `avatar_src(profile_user, "lg")` and pass the result to the avatar() macro,
# which draws the default silhouette when it's None — so no template needs to
# know anything about Cloudinary, media rows, or whether uploads are configured.
#
# Wrapped rather than registered directly because the service takes `size` as
# keyword-only (right for Python callers, where a bare "lg" says nothing) while
# a template reads better positionally.
templates.env.globals["avatar_src"] = lambda user, size="sm": avatar_service.avatar_url(
    user, size=size
)

# A feature flag, not a secret: whether this install can accept photo uploads at
# all. Templates use it to render an honest "not set up on this server" state
# instead of a camera button that 503s. The credentials themselves stay in
# settings and never reach a template.
templates.env.globals["media_enabled"] = settings.media_enabled

# How a price reads, in one function. The `money()` macro in partials/ui.html
# calls this, and `catalog.browse_index()` uses it to pre-format the prices it
# hands to the browser — so a price rendered by Jinja and the same price printed
# by JavaScript come out of one implementation instead of two.
templates.env.globals["naira"] = catalog.naira

# How a TIMESTAMP reads, in one function, for the same reason. `time_ago` gives
# the compact age a dense row wants ("2h"); `absolute_time` gives the exact
# instant that goes in its `title`, because "2w" is honest but imprecise. Both
# tolerate the naive datetimes SQLite hands back (see app/core/timeutils.py).
templates.env.globals["time_ago"] = timeutils.time_ago
templates.env.globals["absolute_time"] = timeutils.absolute_time


def _page_ctx(user: User | None, **extra) -> dict:
    """Context for the in-app (non-bare) pages. Injects the resolved
    current_user into every one so the shared chrome (sidebar profile, top bar)
    renders real identity when signed in and a signed-out state otherwise —
    keeping the key name in one place so the five routes can't drift. `extra`
    carries page_title / active_nav."""
    return {"current_user": user, **extra}


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # The feed carries the catalogue because its posts TAG products (doc 06 §10).
    # A post holds a slug and nothing else; name, price and image are looked up
    # from `product_map` at render time, so a product tagged in the feed and the
    # same product on its own page always quote the same number — and every tag
    # is a real link to /product/{slug} rather than a modal repeating the facts.
    #
    # `feed_posts` comes from the posts table (0014_posts), not from a literal in
    # the template. That is what makes the same post appear here and on its
    # author's profile, and what makes a like count a real number.
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context=_page_ctx(
            user,
            page_title="Home",
            active_nav="home",
            feed_posts=await posts_service.feed(db, viewer=user),
            # The composer shows its photo control only when the server can store
            # a photo, so an install without Cloudinary renders a caption box
            # instead of a button that answers 503.
            media_enabled=settings.media_enabled,
            **(await catalog.catalog_context(db)),
        ),
    )


@router.get("/create", response_class=HTMLResponse)
async def create_post_page(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """The Create Post screen (doc 06 §4-7).

    Signed out, this redirects rather than rendering a form that would answer 401
    on submit — and it says where to come back to, so logging in lands the person
    in the composer they asked for instead of on the feed.

    No seller check: doc 06 §6 gives students image and text posts. Only the
    product-tagging half of posting belongs to businesses, and that is a control
    this screen does not offer rather than an account rule it enforces.
    """
    if user is None:
        return RedirectResponse("/login?next=/create", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="composer.html",
        context=_page_ctx(
            user,
            page_title="New post",
            active_nav="create",
            media_enabled=settings.media_enabled,
            max_images=posts_service.MAX_POST_IMAGES,
        ),
    )


# --- Signup / organization directory (Milestone 1) --------------------

@router.get("/signup", response_class=HTMLResponse)
async def signup(request: Request, google: str | None = Query(default=None)):
    # `google` is a finish-signup token minted by the OAuth callback for a NEW
    # Google user. We verify it HERE only to prefill the locked email + name and
    # switch the form into finish-signup mode — the token itself is echoed back
    # in the form and RE-verified server-side at POST /api/auth/signup, so this
    # render is purely cosmetic and a bad/expired token just falls back to the
    # normal password form. Only the boolean google_oauth flag (never secrets)
    # otherwise reaches the template.
    google_identity = None
    if google:
        try:
            google_identity = google_oauth.verify_finish_signup_token(google)
        except ValidationAppError:
            # Stale/tampered token → render the ordinary signup form rather than
            # a broken finish-signup state. The user can restart Google sign-in.
            google_identity = None

    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={
            "page_title": "Sign Up",
            "active_nav": None,
            "bare": True,
            "google_oauth": settings.google_oauth_enabled,
            # Only set in finish-signup mode; carries the (verified) token to
            # re-submit plus the values to prefill/lock.
            "google_token": google if google_identity else None,
            "google_email": google_identity["email"] if google_identity else None,
            "google_name": google_identity["name"] if google_identity else None,
        },
    )


def _safe_next(target: str | None) -> str | None:
    """Sanitize a `?next=` destination, or None if it isn't ours.

    An unchecked one is an open redirect: `/login?next=https://evil.example`
    turns our own login page into a credible way to bounce a user off-site right
    after they've typed a password. So this accepts only a path on this host —

      * must start with a single `/`
      * must NOT start with `//` (protocol-relative: `//evil.example` is an
        absolute URL to another host that merely looks like a path)
      * no backslashes (some clients normalize `\\` to `/`, so `/\\evil.example`
        can escape a naive check)
      * no control characters, and a sane length cap

    Anything else is dropped rather than repaired — a rejected `next` costs the
    user one extra tap, while a repaired one is a guess about intent.
    """
    if not target or len(target) > 512:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    if "\\" in target or any(ch < " " or ch == "\x7f" for ch in target):
        return None
    return target


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request, next: str | None = Query(default=None)):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "page_title": "Log In",
            "active_nav": None,
            "bare": True,
            "google_oauth": settings.google_oauth_enabled,
            # Where to land after a successful login. Sanitized here (never in
            # the template) so the page can't be turned into an open redirect;
            # None means the default destination.
            "next_url": _safe_next(next),
        },
    )


# --- Password reset / email verification ------------------------------
# All three are `bare`: someone arriving from an email is mid-flow and has
# no business seeing navigation into the rest of the app.

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"page_title": "Forgot Password", "active_nav": None, "bare": True},
    )


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password(request: Request):
    """Landing page for the emailed reset link and for the verified-OTP path.

    The token in ?token= is deliberately not read server-side here — the
    page validates it over the API instead, so a raw credential never
    lands in this app's request logs or in a rendered template.
    """
    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={"page_title": "Set a New Password", "active_nav": None, "bare": True},
    )


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="verify_email.html",
        context={"page_title": "Verify Email", "active_nav": None, "bare": True},
    )


@router.get("/universities", response_class=HTMLResponse)
async def universities_directory(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="universities_directory.html",
        context={"page_title": "University Directory", "active_nav": None, "bare": True},
    )


@router.get("/request-organization", response_class=HTMLResponse)
async def request_organization(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="request_organization.html",
        context={"page_title": "Request a University", "active_nav": None, "bare": True},
    )


# --- Discover ---------------------------------------------------------

@router.get("/discover", response_class=HTMLResponse)
async def discover(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
    q: str | None = Query(default=None, max_length=100),
    tag: str | None = Query(default=None, max_length=60),
):
    """Discover — exploration hub with the universal search (docs/product/07).

    Both query params exist because the feed already links here: `_caption_html`
    sends #hashtags to `?tag=` and @mentions to `?q=%40handle`. They collapse
    into a single `initial_query` the template prefills the search box with, so
    the page runs that search on load instead of opening on a generic explore
    view. `q` wins if both are given.

    The value is only ever rendered into an HTML attribute (Jinja autoescapes
    it) and searched client-side — there's no search backend to pass it to yet,
    so nothing here interpolates it into a query. Lengths are capped so a
    hand-crafted URL can't push an unbounded string into the page.

    The catalogue comes along because products are one of the five searchable
    entity types (doc 07 §5). Discover used to keep its own six-product list;
    reading the real catalogue means a product found by search links to
    /product/{slug} and shows the price its own page shows.
    """
    initial_query = (q or "").strip()
    if not initial_query and tag:
        # A hashtag arrives bare (`?tag=CampusWear`); the search box expects the
        # sigil, which is also what tells the client to rank hashtags first.
        initial_query = "#" + tag.strip().lstrip("#")

    return templates.TemplateResponse(
        request=request,
        name="discover.html",
        context=_page_ctx(
            user,
            page_title="Discover",
            active_nav="discover",
            initial_query=initial_query,
            **(await catalog.catalog_context(db)),
        ),
    )


# --- Profiles ---------------------------------------------------------


@router.get("/@{username}", response_class=HTMLResponse)
async def profile(
    request: Request,
    username: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """A public profile at `/@handle` (doc 08).

    The literal `@` is what makes this safe to declare: the pattern
    `/@{username}` can only ever match a path whose first character is `@`, so
    the namespace is disjoint from `/discover`, `/marketplace`, `/orders` and
    every other route regardless of registration order. A bare `/{username}`
    would shadow all of them and must never be added.

    Three behaviours worth naming:

    *Canonical casing.* Usernames are matched case-insensitively (on
    `username_normalized`) but stored with the casing the user typed. When the
    URL's casing differs we redirect to the stored form, so one profile has one
    URL and shared links converge.

    It is a **302, not a 301** — deliberately, and this is the reason: handles
    became editable on /settings, so a redirect target can stop being valid.
    Suppose `@Ada` renames to `@Lovelace` and someone else signs up as `ada`.
    A cached permanent redirect from `/@ada` → `/@Ada` would send every visitor
    to a handle nobody owns, 404ing the new account at its own URL for as long as
    the browser kept the entry. A temporary redirect costs one revalidation and
    can never outlive the name it points at.

    *A rendered 404, not a JSON envelope.* `register_exception_handlers` turns
    every `AppException` into JSON, which is right for the API and wrong for a
    human who followed an @mention. The NotFoundError is caught here and
    answered with a real page, still at status 404.

    *No status leak.* Unknown, soft-deleted, suspended and blocked handles are
    indistinguishable — all four take the same branch, so no response confirms
    that a hidden account exists or that a block is why the page is missing.
    """
    try:
        profile_user = await follow_service.resolve_public_user(
            db, username=username, viewer_id=user.id if user else None
        )
    except NotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="profile_not_found.html",
            context=_page_ctx(
                user,
                page_title="Profile not found",
                active_nav=None,
                # Length-capped before it reaches the page; Jinja escapes it.
                handle=(username or "")[:30],
            ),
            status_code=404,
        )

    if profile_user.username != username:
        # 302, not 301 — see the docstring. Handles are editable, so a permanent
        # redirect could outlive the name it points at.
        return RedirectResponse(f"/@{profile_user.username}", status_code=302)

    is_own_profile = user is not None and user.id == profile_user.id

    stats = await follow_service.get_profile_stats(
        db,
        user_id=profile_user.id,
        viewer_id=user.id if user else None,
    )

    # A student who sells keeps their school as `organization` — the business is
    # a separate row they own. Fetch it only for sellers (one extra query, and
    # only on profiles that have something to show for it).
    profile_business = None
    if profile_user.is_seller:
        profile_business = await OrganizationRepository(db).get_owned_by_user(
            profile_user.id
        )

    # What this account has actually made. Read here rather than in the template
    # for the same reason the Hub's listings are: an empty list is the only thing
    # that produces an empty state, so "No products yet" can never be shown next
    # to a shop that has eight of them (which is what the profile did before).
    profile_products = (
        await products_service.list_for_business(db, business=profile_business)
        if profile_business is not None
        else []
    )
    profile_posts = await posts_service.by_author(
        db, author_id=profile_user.id, viewer=user
    )
    # Liked is PRIVATE: computed only for the owner, so a visitor's HTML never
    # contains it at all (the tab is not rendered for them either).
    liked_posts = (
        await posts_service.liked_by_user(db, user_id=profile_user.id, viewer=user)
        if is_own_profile
        else []
    )

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context=_page_ctx(
            user,
            page_title=profile_user.display_name,
            active_nav="profile" if is_own_profile else None,
            profile_user=profile_user,
            # The affiliation shown under the name: a student's school, or a
            # brand's own organization.
            profile_org=profile_user.organization,
            profile_business=profile_business,
            profile_products=profile_products,
            profile_posts=profile_posts,
            liked_posts=liked_posts,
            stats=stats,
            is_own_profile=is_own_profile,
            # Keyed on the CAPABILITY, not account_type — a student who sells
            # needs the Products/Reviews tabs as much as a brand does. Mirrors
            # the identity-vs-capability split in app/models/user.py.
            is_business_profile=bool(profile_user.is_seller),
            # Absolute, and from configuration rather than request.base_url —
            # the latter comes from the Host header, so a spoofed one would end
            # up inside a link the user copies and shares.
            share_url=f"{settings.APP_BASE_URL.rstrip('/')}/@{profile_user.username}",
        ),
    )


# --- Shop -------------------------------------------------------------

@router.get("/marketplace", response_class=HTMLResponse)
async def marketplace(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """The marketplace (docs/product/12-shop-and-products.md).

    Titled "Shop" in the UI (sidebar, bottom tab, page title) — the shorter word
    is what the app calls it. The /marketplace PATH stays as-is so existing links
    and the cart affordance in base.html keep working.

    The grid renders rows from the `products` table (0013_products). It used to
    render a curated list in app/services/catalog.py; that module kept its return
    shape when it went query-backed, which is why this route only had to grow a
    `db` dependency and an `await` and the markup did not move.
    """
    return templates.TemplateResponse(
        request=request,
        name="shop.html",
        context=_page_ctx(
            user,
            page_title="Shop",
            active_nav="marketplace",
            # Which gateways the cart footer may offer. Passed from settings so a
            # deployment with only one key shows no picker instead of a dead one.
            payment_providers=payments_service.enabled_providers(),
            **(await catalog.catalog_context(db)),
        ),
    )


@router.get("/product/{slug}", response_class=HTMLResponse)
async def product_detail(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """One product, at its own URL (docs/product/12-shop-and-products.md §5).

    This used to be a modal on /marketplace, and the modal is why it moved: a
    product carries a name, a seller, a rating, a price pair, a description,
    delivery coverage, a pickup point, a quantity control and a related rail,
    and a sheet the width of a phone stacks all of that into one narrow column
    you have to scroll through. A page can put the photo beside the facts, which
    is what every catalogue on the web does because it is what reads well.

    Two consequences worth naming:

    *Products are now shareable.* Before this route the Shop's share button had
    to say "product links arrive with product pages" and copy the Shop's URL.
    `/product/{slug}` is that link.

    *The slug is resolved here, not in the template.* An unknown one gets a
    rendered 404 rather than the JSON envelope `register_exception_handlers`
    produces — same reasoning as the profile route, since a person who followed
    a stale product link is not an API client.

    `products` rides along in the context because the page's related rail and
    the cart both read the catalogue; `catalog_context()` keeps that list
    identical to the one the Shop grid renders.
    """
    try:
        product = await catalog.get_product(db, slug)
    except NotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="product_not_found.html",
            context=_page_ctx(
                user,
                page_title="Product not found",
                active_nav="marketplace",
                # Length-capped before it reaches the page; Jinja escapes it.
                slug=(slug or "")[:60],
                # The 404 offers real alternatives rather than a dead end, so it
                # needs the catalogue too.
                products=await catalog.list_products(db),
            ),
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="product.html",
        context=_page_ctx(
            user,
            page_title=product["name"],
            active_nav="marketplace",
            product=product,
            discount=catalog.discount_percent(product),
            related=await catalog.related_products(db, product),
            # Absolute, and from configuration rather than request.base_url —
            # the latter comes from the Host header, so a spoofed one would end
            # up inside a link the user copies and shares.
            share_url=f"{settings.APP_BASE_URL.rstrip('/')}/product/{product['slug']}",
            **(await catalog.catalog_context(db)),
        ),
    )


# --- Business Hub -----------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """The Business Hub (docs/product/16-business-hub.md).

    Three server-rendered states, decided here rather than hidden with CSS so a
    visitor's HTML never contains a hub they can't use:

      - signed out           → a log-in prompt.
      - signed in, no shop   → the "Start selling" CTA (doc 16 §3). Their
                               account type does NOT change when they accept.
      - owns a business      → the hub itself.

    The gate is the ORGANIZATION ROW, not `users.is_seller`. `owner_user_id` is
    the source of truth and `is_seller` only mirrors it (see
    app/models/user.py); if the two ever drift, a hub rendered off the flag
    would have no business to manage. Fetching the row is also what the page
    needs anyway — the name, state and pickup address are the only editable
    fields it has.

    `stats` is real (followers/following from `user_follows`). Everything else
    doc 16 asks for — revenue, escrow, orders, inventory, analytics, payouts,
    reviews — has no table yet (§30 lists seven that don't exist), so the
    template renders honest zeros and empty states. It must never render the
    ₦48,200 example figure from §6 as if it were this seller's revenue.
    """
    business = None
    stats = None
    catalog_stats = None
    # The seller's own listings and their unread count. Both panels used to say
    # the feature did not exist — copy that was true when it was written and a
    # contradiction by the time the products slice and messaging shipped. They
    # are fetched here (not in the template) so the panel renders rows, and an
    # empty list is the only thing that produces the empty state.
    business_products: list[dict] = []
    unread_messages = 0
    if user is not None:
        # Unread is per-VIEWER (it is every thread with something new), not
        # per-shop, so it is read outside the `business is not None` branch.
        unread_messages = await messaging_service.unread_count(db, viewer=user)
        business = await OrganizationRepository(db).get_owned_by_user(user.id)
        if business is not None:
            # viewer_id=None: the hub shows counts only, so the extra
            # "is the viewer following?" subquery would be wasted work.
            stats = await follow_service.get_profile_stats(
                db, user_id=user.id, viewer_id=None
            )
            # The Hub's ONE metric that products can answer honestly: how many
            # listings are live and how much stock they hold. Sales, revenue and
            # escrow need orders and payments, so they stay at zero and the
            # template says why.
            catalog_stats = await products_service.stats_for_business(db, business=business)
            # Drafts included: the owner's own view is the one place a draft is
            # visible, and `by_owner` is the only listing query that returns them.
            business_products = await products_service.list_for_business(
                db, business=business
            )

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=_page_ctx(
            user,
            page_title="Business Hub",
            active_nav="dashboard",
            business=business,
            stats=stats,
            catalog_stats=catalog_stats,
            business_products=business_products,
            unread_messages=unread_messages,
            # The seller's own public profile, absolute and from configuration
            # rather than request.base_url — the latter comes from the Host
            # header, so a spoofed one would end up in a link they share.
            share_url=(
                f"{settings.APP_BASE_URL.rstrip('/')}/@{user.username}" if user else None
            ),
        ),
    )


# --- Orders -----------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Account settings — everything that acts on the ACCOUNT rather than on a
    profile someone is looking at.

    The split is the whole design. `/@handle` is a public page about an identity;
    this is a private page about a login. So the profile keeps what a visitor
    could meaningfully see (photo, names, bio, follow, share) and everything else
    — starting to sell, graduation, email, password, theme, log out — lives here,
    reachable from the profile's ⋯ sheet and the gear in its top bar.

    **Signed out is a redirect, not a 401.** Every other page on the site renders
    a signed-out state, but there is no useful anonymous rendering of "your
    settings"; sending someone to /login is the honest answer, and `next=`
    returns them here afterwards.

    `business` is resolved through `owner_user_id` rather than `users.is_seller`,
    the same gate /dashboard and /orders use: the flag is a denormalized mirror
    and the page must follow the row that actually exists. Its only job here is
    choosing between "Start selling" (a form) and "Business Hub" (a link).
    """
    if user is None:
        return RedirectResponse("/login?next=/settings", status_code=302)

    business = await OrganizationRepository(db).get_owned_by_user(user.id)

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=_page_ctx(
            user,
            page_title="Settings",
            active_nav="settings",
            business=business,
            # Read here, not in the template: whether the account can take a
            # photo at all is a server fact, and the identity block renders a
            # different control depending on it.
            has_photo=avatar_service.avatar_url(user) is not None,
        ),
    )


@router.get("/orders", response_class=HTMLResponse)
async def orders(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Orders — the buyer's side of a purchase (docs/product/14-orders-and-delivery.md).

    Nothing is fetched because nothing is fetchable: doc 14 §25 names six tables
    (orders, order_items, order_status_history, deliveries, disputes, refunds)
    and none of them exists, nor do products, a cart, or a payment record. The
    template therefore renders the four §18 history tabs honestly EMPTY plus the
    rules doc 14 actually specifies — the lifecycle, what each status and escrow
    state means, pickup vs seller delivery, the 72-hour auto-release, and how
    disputes/cancellations work.

    It must not render a specimen order. A fake order card carries a business
    name, an amount and an escrow state, so it reads as a claim about the user's
    own money — the same rule that keeps §6's example revenue figure off the
    Business Hub, only stricter.

    The one query is real: a seller's INCOMING orders belong to the Business Hub
    (§6), not here, so someone who owns a business gets a card pointing at
    /dashboard#orders rather than being left to wonder where they went. Gated on
    the org row rather than `users.is_seller` for the same reason the Hub is —
    the flag is a denormalized mirror and can drift.
    """
    business = None
    payments: list[dict] = []
    if user is not None:
        business = await OrganizationRepository(db).get_owned_by_user(user.id)
        # Real rows now that Flutterwave is connected: every checkout attempt is
        # a payment, and a successful one belongs on this page. The behavioural
        # panels below the list are unchanged — they explain the same system.
        payments = [
            payments_service.to_receipt(p)
            for p in await payments_service.for_user(db, user.id)
        ]

    counts = {"current": 0, "completed": 0, "cancelled": 0, "refunded": 0}
    for row in payments:
        counts[row["tab"]] = counts.get(row["tab"], 0) + 1

    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context=_page_ctx(
            user,
            page_title="Orders",
            active_nav="orders",
            business=business,
            payments=payments,
            payment_counts=counts,
        ),
    )


# --- Activity / Messages ----------------------------------------------

# How many activity rows one render carries, and the ceiling "Show more" can
# grow the window to. Cumulative rather than paged (see the route's docstring),
# so the cap is what stops a 4,000-follower account rendering 4,000 rows.
ACTIVITY_PAGE_SIZE = 20
ACTIVITY_MAX = 200


@router.get("/notifications", response_class=HTMLResponse)
async def notifications(
    request: Request,
    show: int = Query(default=ACTIVITY_PAGE_SIZE, ge=1, le=ACTIVITY_MAX),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Activity — the inbox behind the bell (docs/product/11-activity-and-notifications.md).

    **One category is real, and exactly one.** Doc 11 §4 lists six (Social, Shop,
    Orders, Events, Business, System) and its own implementation note says why
    only one can be built today: there is no `notifications` table, and almost
    every event such a table would carry — a like, a comment, a mention, an order
    status change, an escrow release, a ticket sale — needs its own table first.
    Follows are the exception. `user_follows` is real, so "X started following
    you" is a genuine notification, rendered from the edge itself.

    That is why this page queries the FOLLOW GRAPH rather than a notifications
    store. `list_followers` already returns the edge's `created_at` as
    `followed_at` (app/services/follow.py) — its docstring anticipated this
    exact caller — so a row costs no extra query, and `is_following` on the same
    row is what makes the Follow-back button render in the right state without a
    request per row.

    **No read state, and no unread badge.** Doc §12-13 want both, and both are
    server state with nowhere to live: a localStorage flag would claim "read" on
    one device and "unread" on another for the same event, and a badge counting
    total followers would re-alarm every time you cleared it. The page says so in
    the pending list instead of faking it.

    **`show` grows the window; it does not page it.** An activity list is read
    top-down, so the second screenful must not replace the first — `?show=40`
    re-renders rows 1-40 and the anchor puts you back where you were. That is
    the no-JavaScript equivalent of appending, and it keeps every timestamp
    formatted by one function on the server. FastAPI clamps it to 1-200, so a
    hand-typed `?show=99999` is a 422 rather than a full-table render.

    Signed out is a redirect, not an anonymous state: "your activity" has no
    useful public rendering, same reasoning as /settings.
    """
    if user is None:
        return RedirectResponse("/login?next=/notifications", status_code=302)

    follows = await follow_service.list_followers(
        db, user_id=user.id, viewer_id=user.id, limit=show
    )

    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context=_page_ctx(
            user,
            page_title="Activity",
            active_nav="notifications",
            follow_rows=follows.items,
            follow_total=follows.total,
            # Whether a "Show more" link is worth drawing, and where it points.
            # Computed here because it is a pagination fact, not a layout one.
            shown=len(follows.items),
            next_show=min(show + ACTIVITY_PAGE_SIZE, ACTIVITY_MAX),
            has_more=follows.total > len(follows.items) and show < ACTIVITY_MAX,
        ),
    )


@router.get("/messages", response_class=HTMLResponse)
async def messages(
    request: Request,
    share: str | None = Query(default=None, max_length=140),
    share_user: str | None = Query(default=None, max_length=40),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Messages — the inbox (docs/product/10-messaging.md).

    This route used to render a reference card and say so: doc 10 §26's tables
    did not exist, so the page explained the rules instead of enforcing them.
    They exist now — `conversations`, `conversation_participants`, `messages`,
    a socket at /ws/messages, and every endpoint in §27 — so the page is the
    feature.

    It still fetches almost nothing, but for the opposite reason. The inbox and
    the open thread both arrive from /api/messages, and they have to, because
    both also arrive over a socket: a new message reorders the list, rewrites a
    preview and bumps a count. Server-rendering the first paint would mean two
    renderers for one row and a day when they disagree. So the template is
    furniture and the data is one fetch behind it. See messages.html's header.

    The `business` query is real, and it is the same gate /orders, /settings and
    /dashboard use. Doc §3-4 allow Student↔Business and Business↔Business
    conversations, so a seller's inbox carries customer enquiries alongside their
    own conversations.

    Report reasons are passed down rather than written into the template, so the
    radio group in the report sheet is the same tuple the API validates against.

    `?share=<product-slug>` and `?share_user=<handle>` are how a Share sheet
    elsewhere in the app hands something to the compose picker: pick a person and
    the client POSTs a `shared_product` or `shared_profile` message. NOTHING IS
    SENT HERE. A GET that sent a message would fire again on a refresh, on a back
    button, and on any prefetch the browser felt like doing, so the value is
    passed to the template as data and the send stays a POST. It is not validated
    either — an unknown slug or handle fails at that POST with the API's own
    wording rather than 422-ing a page the user can still use for everything else.

    Signed out is a redirect (same reasoning as /settings and /notifications):
    an inbox has no useful anonymous rendering.
    """
    if user is None:
        return RedirectResponse("/login?next=/messages", status_code=302)

    return await _render_messages(
        request,
        db,
        user,
        open_handle=None,
        share_slug=share,
        share_user=share_user,
    )


@router.get("/messages/@{username}", response_class=HTMLResponse)
async def message_thread(
    username: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """One conversation, deep-linked — what the profile's Message button opens.

    The same page as /messages with a handle handed to the client, not a
    different one: the thread pane is part of the inbox shell, and at lg+ the
    list stays on screen beside it. Rendering a standalone thread page would mean
    a second copy of that shell and a desktop layout that loses its own sidebar
    when you open a message.

    NOTHING IS VALIDATED HERE, deliberately. A handle that does not exist, an
    account that suspended itself, someone who blocked you — all three get this
    page, and the 404 comes from the thread fetch a moment later. Checking here
    would mean this route returning 404 for a blocked account and 200 for a
    stranger, which is exactly the tell §22 spends the whole service layer
    avoiding: the URL would answer a question the API refuses to.

    A conversation does not have to exist yet. Open /messages/@someone you have
    never written to and the thread pane comes up empty with a live composer,
    because the conversation is created by the first send (§6), not by looking.
    """
    if user is None:
        return RedirectResponse(
            f"/login?next=/messages/@{username}", status_code=302
        )

    return await _render_messages(request, db, user, open_handle=username)


async def _render_messages(
    request: Request,
    db: AsyncSession,
    user: User,
    *,
    open_handle: str | None,
    share_slug: str | None = None,
    share_user: str | None = None,
) -> HTMLResponse:
    """The shared body of /messages and /messages/@{handle}."""
    business = await OrganizationRepository(db).get_owned_by_user(user.id)

    return templates.TemplateResponse(
        request=request,
        name="messages.html",
        context=_page_ctx(
            user,
            page_title="Messages",
            active_nav="messages",
            business=business,
            open_handle=open_handle,
            share_slug=share_slug,
            share_user=share_user,
            report_reasons=[
                (reason, REPORT_REASON_LABELS.get(reason, reason.title()))
                for reason in REPORT_REASONS
            ],
        ),
    )
