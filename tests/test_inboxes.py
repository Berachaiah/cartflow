"""
The two inbox pages: /notifications and /messages.

Both were toast buttons in Home's top bar until August 17. They have since gone in
opposite directions, and what each one renders is the interesting part:

  - /notifications still has no table of its own. It carries exactly ONE real
    notification type, "@x started following you", read from the follow graph
    rather than from a notifications store. Its whole value is that it is real, so
    the test that matters is the one that creates an actual follow edge and looks
    for the row.

  - /messages has all of its tables now — `conversations`,
    `conversation_participants`, `messages`, `user_blocks` — and the assertion has
    inverted with them. It used to be that the page must invent no conversation
    because there were none to render. It must still invent none, but now because
    every row and every bubble is drawn by cartflow-messages.js from the API: a row
    also arrives over a socket, so a Jinja copy would be a second renderer for the
    same row and the two would eventually disagree. So the tests here assert that
    the HTML arrives as an empty shell, that the controls on it are the ones the
    API can actually honour, and that /messages/@{handle} answers nothing the API
    refuses to (§22). What a conversation *does* lives in test_messaging.py.

Both redirect when signed out, because "your activity" and "your inbox" have no
useful anonymous rendering — same reasoning as /settings.

Rows are inserted directly rather than built through signup + the follow API.
Two reasons: these tests are about what the page renders, not about how the edge
got there (same call the follow tests make), and a `display_name` set by hand is
one the assertion can actually name. `me` still signs in for real, because the
session is the thing under test on a redirect.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import absolute_time, time_ago
from app.models.user import AccountStatus, AccountType, User, UserFollow

PAGES = ["/notifications", "/messages"]
PASSWORD = "password123"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


# --- helpers -------------------------------------------------------------

def _visible(page: str) -> str:
    """The response with HTML comments stripped.

    Jinja removes `{# ... #}` but passes `<!-- ... -->` straight through to the
    browser, and these templates comment heavily — notifications.html explains
    *why* "Show more" carries an #activity anchor in a comment a few lines above
    the link. So an absence assertion against the raw response finds the
    explanation and reports the feature as present. Use this for "not in";
    presence assertions can read the raw text.
    """
    return _HTML_COMMENT.sub("", page)

async def _signup(client: AsyncClient, username: str, **extra) -> None:
    payload = {
        "role": "individual",
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


async def _sign_in(client: AsyncClient, username: str = "ada") -> None:
    await _signup(client, username)
    await _login(client, username)


async def _fetch(db: AsyncSession, username: str) -> User:
    """The signed-in user's row, so follow edges can point at its real id."""
    user = (
        await db.execute(select(User).where(User.username_normalized == username.lower()))
    ).scalar_one()
    return user


async def _make_user(db: AsyncSession, username: str, **extra) -> User:
    user = User(
        account_type=AccountType.INDIVIDUAL,
        account_status=AccountStatus.ACTIVE,
        email=f"{username}@example.com",
        password_hash=None,
        username=username,
        username_normalized=username.lower(),
        display_name=extra.pop("display_name", f"{username.title()} Person"),
        **extra,
    )
    db.add(user)
    await db.flush()
    return user


async def _followed_by(db: AsyncSession, target: User, fan: User, *, mutual: bool = False) -> None:
    db.add(UserFollow(follower_id=fan.id, following_id=target.id))
    if mutual:
        db.add(UserFollow(follower_id=target.id, following_id=fan.id))
    await db.commit()


# --- signed out ----------------------------------------------------------

@pytest.mark.parametrize("path", PAGES)
async def test_signed_out_redirects_back_to_itself(client: AsyncClient, path: str):
    """302 with ?next= — not a 401, and not an anonymous render.

    The `next` round-trip is the point: someone who tapped the bell should land
    on the bell after logging in, not on the home feed.
    """
    r = await client.get(path)
    assert r.status_code == 302, f"{path} returned {r.status_code}, expected a redirect"
    assert r.headers["location"] == f"/login?next={path}", (
        f"{path} redirects to {r.headers['location']!r}, losing where the user was going"
    )


# --- /notifications: the one real notification ---------------------------

async def test_a_real_follow_renders_as_a_notification(client: AsyncClient, db: AsyncSession):
    """The only notification the app can honestly produce today."""
    await _sign_in(client)
    fan = await _make_user(db, "adaeze", display_name="Adaeze Okonkwo")
    await _followed_by(db, await _fetch(db, "ada"), fan)

    r = await client.get("/notifications")
    assert r.status_code == 200, r.text
    assert "@adaeze" in r.text, "the follower's handle is missing — it is what identifies them"
    assert "started following you" in r.text, (
        "the notification lost its verb phrase; a name and a timestamp alone do not say "
        "what happened"
    )
    assert "Adaeze Okonkwo" in r.text, "the display name is missing from the row's meta line"
    # The rendered span, not the bare words: the follow-toggle script at the foot of
    # the page contains both labels as string literals, so a plain substring search
    # finds "Follow back" on a page that never draws it.
    assert "<span data-follow-label>Follow back</span>" in r.text, (
        "no Follow-back control. `list_followers` returns `is_following` on the same row "
        "precisely so this renders in the right state without a request per row"
    )
    assert 'data-handle="adaeze"' in r.text, (
        "the Follow-back button carries no handle, so its POST has no target"
    )


async def test_follow_back_reads_the_existing_edge(client: AsyncClient, db: AsyncSession):
    """A mutual follow must render 'Following', not an invitation to follow again.

    Seeded server-side rather than fetched per row, and this is the assertion that
    catches it being dropped: 'Follow back' on someone you already follow turns
    the button into an unfollow that nobody asked for.
    """
    await _sign_in(client)
    friend = await _make_user(db, "chidi", display_name="Chidi Eze")
    await _followed_by(db, await _fetch(db, "ada"), friend, mutual=True)

    r = await client.get("/notifications")
    assert r.status_code == 200, r.text
    assert 'data-following="true"' in r.text, (
        "the row does not know the viewer already follows back, so a reload would lose the state"
    )
    assert "<span data-follow-label>Following</span>" in r.text, (
        "the button renders the wrong label for an edge that already exists"
    )
    assert "<span data-follow-label>Follow back</span>" not in r.text, (
        "a mutual follow is still being offered 'Follow back', so the button would undo a "
        "follow the user already has"
    )


async def test_the_empty_state_says_what_it_is_waiting_on(client: AsyncClient):
    await _sign_in(client)
    r = await client.get("/notifications")
    assert r.status_code == 200, r.text
    assert "No followers yet" in r.text, (
        "an activity inbox with nothing in it must say so; a blank panel reads as a failed request"
    )
    assert "Show more" not in _visible(r.text), (
        "a 'Show more' link on an empty inbox points at the same empty inbox"
    )


# --- /notifications: the show window ------------------------------------

@pytest.mark.parametrize(
    "show,expected",
    [
        (1, 200),
        (20, 200),
        (200, 200),
        (0, 422),        # ge=1
        (201, 422),      # le=200
        (99999, 422),    # the hand-typed one
        (-5, 422),
    ],
)
async def test_show_is_clamped_at_the_boundary(client: AsyncClient, show: int, expected: int):
    """`show` grows the window; it must never become a full-table render.

    An activity list is read top-down, so `?show=40` re-renders rows 1-40 rather
    than replacing them with 21-40 — which makes the parameter a row count, and an
    unclamped row count is a denial of service with a query string.
    """
    await _sign_in(client)
    r = await client.get(f"/notifications?show={show}")
    assert r.status_code == expected, f"?show={show} returned {r.status_code}, expected {expected}"


async def test_the_window_holds_one_screenful_and_offers_the_next(
    client: AsyncClient, db: AsyncSession
):
    """21 followers: 20 rows and a link that grows the window to 40.

    The link must GROW rather than page — `?show=40` re-renders the first 20 as
    well — so the count in the label reads "20 of 21", not "page 1 of 2".
    """
    await _sign_in(client)
    me = await _fetch(db, "ada")
    for i in range(21):
        db.add(UserFollow(follower_id=(await _make_user(db, f"fan{i:02d}")).id, following_id=me.id))
    await db.commit()

    r = await client.get("/notifications")
    assert r.status_code == 200, r.text
    rows = r.text.count("started following you")
    assert rows == 20, f"rendered {rows} rows; the window is 20 (ACTIVITY_PAGE_SIZE)"
    assert 'href="/notifications?show=40#activity"' in r.text, (
        "'Show more' does not grow the window by one page, or lost the #activity anchor "
        "that returns you to the list instead of the top of the page"
    )
    assert "(20 of 21)" in r.text, (
        "the label must say how much of the whole is showing — a bare 'Show more' gives no "
        "sense of how much is left"
    )

    grown = await client.get("/notifications?show=40")
    assert grown.text.count("started following you") == 21, (
        "growing the window did not include all 21 rows"
    )
    assert "Show more" not in _visible(grown.text), (
        "'Show more' is still offered with nothing more to show"
    )


# --- the timestamps those rows depend on --------------------------------

def test_time_ago_boundaries():
    """Pinned rather than slept, and checked on both sides of each threshold.

    These strings sit beside the curated feed's literal "2h" / "30m" / "1d", so
    the format is load-bearing: a real timestamp that reads differently from a
    placeholder one looks like two apps' data in one list.
    """
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    cases = [
        (timedelta(seconds=0), "now"),
        (timedelta(seconds=44), "now"),          # last second before minutes
        (timedelta(seconds=45), "0m"),           # first second of minutes
        (timedelta(minutes=59), "59m"),
        (timedelta(minutes=60), "1h"),
        (timedelta(hours=23, minutes=59), "23h"),
        (timedelta(hours=24), "1d"),
        (timedelta(days=6, hours=23), "6d"),
        (timedelta(days=7), "1w"),
        (timedelta(days=34), "4w"),              # last week before it becomes a date
    ]
    for delta, expected in cases:
        got = time_ago(now - delta, now=now)
        assert got == expected, f"{delta} formatted as {got!r}, expected {expected!r}"


def test_time_ago_switches_to_a_date_past_five_weeks():
    """"9w" is a number nobody converts."""
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    # Same year: no year printed, so the common case stays two words wide.
    assert time_ago(datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc), now=now) == "1 Jun"
    # Different year: the year is the thing that disambiguates it.
    assert time_ago(datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc), now=now) == "1 Jun 2025"


def test_a_future_timestamp_reads_as_now():
    """Clock skew between the app server and the database, not a time traveller.

    "in -3m" is a worse answer than rounding to zero, and it is the answer a naive
    subtraction gives.
    """
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert time_ago(now + timedelta(minutes=3), now=now) == "now"


def test_a_naive_timestamp_is_read_as_utc():
    """SQLite hands back naive datetimes, so this is the normal path in tests and
    on the dev-preview database — not an edge case."""
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert time_ago(datetime(2026, 8, 18, 10, 0), now=now) == "2h"


def test_both_helpers_tolerate_none():
    """So a template can render the pair unconditionally, with no {% if %}."""
    assert time_ago(None) == ""
    assert absolute_time(None) == ""


def test_absolute_time_states_its_timezone():
    """The app has no per-user timezone, so presenting a UTC instant as local
    time would be a guess."""
    stamped = absolute_time(datetime(2026, 8, 18, 9, 5, tzinfo=timezone.utc))
    assert stamped == "18 Aug 2026, 09:05 UTC", stamped


async def test_the_row_carries_both_forms(client: AsyncClient, db: AsyncSession):
    """The compact age is what you read; the exact moment is what you occasionally
    want, and it rides along in the `title`."""
    await _sign_in(client)
    fan = await _make_user(db, "ngozi")
    await _followed_by(db, await _fetch(db, "ada"), fan)

    r = await client.get("/notifications")
    assert "<time datetime=" in r.text, "the timestamp is not marked up as a <time>"
    assert " UTC" in r.text, (
        "the row lost its absolute_time() tooltip, so the only timestamp on the page is an "
        "approximation with no way to see the real one"
    )


# --- /messages: a shell, and only a shell -------------------------------

async def test_messages_renders_no_conversation_server_side(client: AsyncClient):
    """ONE RENDERER, asserted.

    Every row and every bubble is drawn by cartflow-messages.js, because every one
    of them also arrives over a socket. A conversation rendered by Jinja as well
    would be a second renderer for the same row, and the day the two disagree is
    the day a message reads differently depending on whether you scrolled to it or
    watched it land. So the invariant is that the HTML arrives with the boxes and
    none of the contents — and it is worth a test because the natural instinct
    when a page loads a beat slowly is to server-render the first paint.
    """
    await _sign_in(client)
    r = await client.get("/messages")
    assert r.status_code == 200, r.text
    body = _visible(r.text)

    assert 'data-inbox-rows class="space-y-0.5"></div>' in body, (
        "the rows container arrived with something in it — the inbox is server-rendered now, "
        "and there are two renderers for one row"
    )
    # The data attributes, not the class names. `.msg-bubble-row` is *styled* in
    # the page's stylesheet and always will be — the CSS for a bubble has to ship
    # with the page that draws bubbles. What must not ship is an instance, and an
    # instance is what carries these.
    for drawn_by_js in ("data-msg=", "data-row=", "data-tick"):
        assert drawn_by_js not in body, (
            f"{drawn_by_js!r} is in the server's HTML. That markup belongs to "
            "cartflow-messages.js — a Jinja copy of it is a second renderer"
        )
    assert "js/cartflow-messages.js" in r.text, (
        "the page no longer loads the only thing that can draw a conversation, so /messages "
        "renders furniture and nothing else forever"
    )


async def test_messages_invents_no_conversation(client: AsyncClient):
    """No specimen thread — the same rule as before the feature existed, for a
    different reason.

    It used to be that a fabricated row could only lead nowhere. Now it would lead
    somewhere real and wrong: /messages/@{handle} resolves, so a placeholder
    "Chidi · is this still available?" opens an actual empty thread with an actual
    person, and the words were never theirs.
    """
    await _sign_in(client)
    r = await client.get("/messages")
    body = _visible(r.text)

    assert 'href="/messages/@' not in body, (
        "a server-rendered link into a thread. Rows are buttons drawn by JS from the API; a "
        "hardcoded one names a person the viewer may not even have a conversation with"
    )
    for fabricated in ("is this still available", "Active now", "2 new", "You: "):
        assert fabricated not in body, (
            f"/messages is showing {fabricated!r} in its server HTML — a preview, a presence "
            "line and an unread count all come from the API, so a literal here is invented"
        )


async def test_messages_explains_the_one_message_rule(client: AsyncClient):
    """Doc 10 §6 — the rule that actually changes how someone behaves.

    Still on the page, and still worth a test, but it has moved: it used to be the
    whole point of the screen and it is now a line in the empty states, said where
    it is about to matter. Reading it before messaging a seller is different from
    discovering it after being ignored.
    """
    await _sign_in(client)
    r = await client.get("/messages")

    assert "goes to their requests until they reply" in r.text, (
        "the empty inbox no longer says where a first message to a stranger goes, which is the "
        "half of §6 that changes what someone types"
    )
    assert "their one message waits here until you reply or delete it" in r.text, (
        "the Requests tab's empty state lost the other half — that the sender gets exactly one "
        "and cannot follow it up"
    )


async def test_messages_offers_the_controls_it_can_now_honour(client: AsyncClient):
    """The inverse of the test this replaces.

    A search field and three tabs over a fake thread list used to be all chrome —
    nothing to search, nothing to filter. Every one of them is now backed by a
    real query parameter on GET /api/messages, so the assertion flips: they have
    to be *present*, and the old "messaging isn't live yet" copy has to be gone
    from every corner of the page.
    """
    await _sign_in(client)
    r = await client.get("/messages")
    body = _visible(r.text)

    assert 'type="search"' in r.text, (
        "the inbox lost its search field. §20 search is real — `?q=` on GET /api/messages — so "
        "hiding the control now understates what the page does"
    )
    for tab in ("all", "unread", "requests"):
        assert f'data-filter="{tab}"' in r.text, f"the {tab!r} tab is gone"
    assert "data-compose-open" in r.text, (
        "nothing on the page starts a new conversation, so the only way in is somebody else's "
        "profile"
    )
    for stale in ("isn&#39;t live yet", "no message is sitting unread", "See your activity"):
        assert stale not in body, (
            f"/messages still says {stale!r}. Messaging shipped — this page is the feature now, "
            "not an explanation of one"
        )


async def test_messages_ships_the_reasons_the_api_validates(client: AsyncClient):
    """The report sheet's radios are the server's own REPORT_REASONS.

    Passed down through the route rather than typed into the template, so the form,
    the API's validator and the admin email cannot drift into three different
    lists — and a reason the user can pick but the API rejects is a 422 at the end
    of a form somebody filled in about being harassed.
    """
    from app.models.report import REPORT_REASONS

    await _sign_in(client)
    r = await client.get("/messages")
    for reason in REPORT_REASONS:
        assert f'value="{reason}"' in r.text, (
            f"the report sheet cannot report {reason!r}, which the API accepts — the template "
            "has its own list again"
        )


# --- /messages/@{handle}: one conversation, deep-linked ------------------

async def test_a_deep_linked_thread_renders_for_a_stranger(client: AsyncClient, db: AsyncSession):
    """No conversation needed. The thread pane opens with a live composer, because
    §6 creates the conversation on the first send, not on looking."""
    await _sign_in(client)
    await _make_user(db, "chidi")
    await db.commit()

    r = await client.get("/messages/@chidi")
    assert r.status_code == 200, r.text
    assert 'data-open-handle="chidi"' in r.text, (
        "the handle never reached the client, so the page opens the inbox and forgets which "
        "conversation the URL asked for"
    )


async def test_the_url_answers_nothing_the_api_refuses_to(client: AsyncClient, db: AsyncSession):
    """§22, at the routing layer.

    A block, a suspended account and a handle that never existed all get this page
    — byte-identical but for the handle itself. Validating here would mean 404 for
    a blocked account and 200 for a stranger, and the URL would then answer the
    one question the whole service layer is built to refuse: whether you have been
    blocked.
    """
    from app.models.conversation import UserBlock

    await _sign_in(client)
    blocker = await _make_user(db, "amara")
    me = await _fetch(db, "ada")
    db.add(UserBlock(blocker_id=blocker.id, blocked_id=me.id))
    await db.commit()

    blocked = await client.get("/messages/@amara")
    ghost = await client.get("/messages/@nobodyatall")
    assert blocked.status_code == ghost.status_code == 200, (
        f"blocked={blocked.status_code} unknown={ghost.status_code} — the status code alone now "
        "tells the viewer they were blocked"
    )
    # Identical once the handle is normalised away. Anything else — a different
    # length, an extra element — is a tell that survives the matching status code.
    assert blocked.text.replace("amara", "X") == ghost.text.replace("nobodyatall", "X"), (
        "the two pages differ beyond the handle in the URL, so the render distinguishes a block "
        "from an account that never existed"
    )


async def test_a_share_link_carries_and_never_sends(client: AsyncClient, db: AsyncSession):
    """`?share=` and `?share_user=` reach the compose picker as data. Nothing is sent.

    This is the invariant the whole share path is built around. A GET that sent a
    message would send it again on a refresh, again on the back button, and again
    on any link prefetch — and the user would have no idea, because the thing that
    fired is a page load. So the query string is handed to the client as a
    `data-*` attribute and the send is a POST from the picker, once, on a tap.

    Also: neither value is validated here. An unknown slug and a handle that does
    not exist both render, because the alternative is /messages answering whether
    an account exists — the same question §22 refuses everywhere else. They fail
    at the POST, in the API's own words.
    """
    from sqlalchemy import func

    from app.models.conversation import Conversation, Message
    from app.services import catalog

    async def _row_counts() -> tuple[int, int]:
        conversations = await db.scalar(select(func.count()).select_from(Conversation))
        messages = await db.scalar(select(func.count()).select_from(Message))
        return conversations or 0, messages or 0

    await _sign_in(client)
    await _make_user(db, "chidi")
    await db.commit()
    assert await _row_counts() == (0, 0), "the fixture database did not start empty"

    # A real catalogue slug, the same one the product page's Send link would carry.
    slug = catalog.list_products()[0]["slug"]
    product = await client.get(f"/messages?share={slug}")
    assert product.status_code == 200, product.text
    assert f'data-share-slug="{slug}"' in product.text

    profile = await client.get("/messages?share_user=chidi")
    assert profile.status_code == 200, profile.text
    assert 'data-share-user="chidi"' in profile.text

    # Unvalidated on purpose — see the docstring.
    for url in ("/messages?share=no-such-product-at-all", "/messages?share_user=nobodyatall"):
        r = await client.get(url)
        assert r.status_code == 200, f"{url} -> {r.status_code}"

    assert await _row_counts() == (0, 0), (
        "a GET on /messages wrote a conversation or a message — a share link that "
        "sends will re-send on every refresh, back button and prefetch"
    )


# --- the entry points ---------------------------------------------------

async def test_home_links_to_both_inboxes(client: AsyncClient):
    """They were toast buttons; a real page needs a real link."""
    await _sign_in(client)
    r = await client.get("/")
    assert r.status_code == 200, r.text
    for href in ('href="/notifications"', 'href="/messages"'):
        assert href in r.text, f"Home's top bar lost {href}"
    # Scoped to these two icons. Home carries other honest "coming soon" toasts —
    # the story composer and event ticketing genuinely aren't built — so a blanket
    # search for the phrase fails on features this test has no opinion about.
    for stale in ("showToast('Activity", "showToast('Messages", "showToast('Inbox"):
        assert stale not in r.text, f"the inbox icon is a toast again: {stale!r}"


async def test_signed_out_home_sends_the_icons_through_login(client: AsyncClient):
    """Not hidden, and not a dead end: the icon points at login and comes back."""
    r = await client.get("/")
    assert r.status_code == 200, r.text
    for href in ('href="/login?next=/notifications"', 'href="/login?next=/messages"'):
        assert href in r.text, f"signed-out Home lost {href}"


async def test_the_sidebar_reaches_both(client: AsyncClient):
    await _sign_in(client)
    r = await client.get("/")
    for href in ('href="/notifications"', 'href="/messages"'):
        assert r.text.count(href) >= 2, (
            f"{href} appears once — the desktop rail and the mobile top bar should both reach it"
        )


@pytest.mark.parametrize("path,nav", [("/notifications", "notifications"), ("/messages", "messages")])
async def test_each_page_marks_its_own_nav_item(client: AsyncClient, path: str, nav: str):
    """Otherwise you arrive somewhere with nothing in the rail lit up, which reads
    as having navigated out of the app."""
    await _sign_in(client)
    r = await client.get(path)
    assert r.status_code == 200, r.text
    assert "active-nav" in r.text, f"{path} lights up no nav item"
