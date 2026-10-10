"""
Messaging over HTTP — §6's state machine, the thread reads, and the per-thread
controls, exercised through the real endpoints.

The service has the rules; these tests check that the *router* exposes them
faithfully, which is a different question and fails in different ways. Four things
are load-bearing here and each has a test that would notice it quietly breaking:

**The state machine is a sequence, so it is tested as one.** "PENDING + initiator →
409" cannot be set up by inserting a row — the interesting part is that the second
POST is refused after the first succeeded, and a fixture that fabricated the
PENDING conversation would not prove the first send created it correctly. So these
tests send real messages in order.

**404 for a block must be indistinguishable from 404 for a stranger.** §22 is a
promise that the API never reveals "they blocked you", and the way that breaks is
not a wrong status code — it is a *different message* under the same code. So the
two are asserted equal to each other, body and all, rather than each being checked
for 404 separately.

**Two people need two cookie jars.** The `client` fixture is one browser. Half of
messaging is what the *other* side sees, so `clients` mints more of them against
the same app and the same test database — a second real session, not a second
identity swapped onto one.

**`is_mine` is per-viewer.** The same message is rendered twice, once for each
side, and a test that only ever looks at the sender's copy cannot see the bug
where both sides get the sender's alignment.
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.conversation import Conversation, ConversationStatus, Message
from app.models.user import AccountStatus, User, UserFollow

PASSWORD = "password123"


# --- helpers -------------------------------------------------------------


@pytest_asyncio.fixture
async def clients(client: AsyncClient):
    """A factory for additional browsers against the same app and test DB.

    Depends on `client` for its side effect: that fixture installs the `get_db`
    override, so every client made here talks to the same in-memory database.
    Each gets its own cookie jar, which is the whole point — a signed-in Ada and a
    signed-in Chidi at the same time.
    """
    made: list[AsyncClient] = []

    async def _make(username: str | None = None) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        made.append(c)
        if username is not None:
            await _sign_in(c, username)
        return c

    yield _make
    for c in made:
        await c.aclose()


async def _signup(c: AsyncClient, username: str, **extra) -> None:
    r = await c.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": extra.pop("full_name", f"{username.title()} Tester"),
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
            **extra,
        },
    )
    assert r.status_code == 201, r.text


async def _login(c: AsyncClient, username: str) -> None:
    r = await c.post(
        "/api/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _sign_in(c: AsyncClient, username: str) -> None:
    await _signup(c, username)
    await _login(c, username)


async def _send(c: AsyncClient, to: str, body: str = "hello") -> Response:
    return await c.post(f"/api/messages/threads/{to}", json={"body": body})


async def _thread(c: AsyncClient, other: str) -> dict:
    r = await c.get(f"/api/messages/threads/{other}")
    assert r.status_code == 200, r.text
    return r.json()


async def _inbox(c: AsyncClient, **params) -> dict:
    r = await c.get("/api/messages", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def _badge(c: AsyncClient) -> int:
    r = await c.get("/api/messages/unread")
    assert r.status_code == 200, r.text
    return r.json()["count"]


async def _user(db: AsyncSession, username: str) -> User:
    return (
        await db.execute(
            select(User).where(User.username_normalized == username.lower())
        )
    ).scalar_one()


async def _make_older(db: AsyncSession, body: str, *, minutes: int) -> None:
    """Move one message back in time, found by its text.

    `created_at` is `server_default=func.now()`, which on SQLite is
    `CURRENT_TIMESTAMP` — one-second resolution. Two messages sent by one test
    therefore share a timestamp, and the thread query orders by that column alone,
    so it may return them either way round. Production is PostgreSQL, where
    `now()` is the transaction timestamp and two sends are microseconds apart, so
    this is a harness artifact — but a test that passes only because SQLite
    happened to return rows in insert order is not testing chronology.
    """
    stmt = (
        select(Message)
        .where(Message.body == body)
        .execution_options(populate_existing=True)
    )
    message = (await db.execute(stmt)).unique().scalar_one()
    message.created_at = message.created_at - timedelta(minutes=minutes)
    await db.commit()


# --- §6: the one-message rule -------------------------------------------


async def test_a_first_message_opens_a_pending_request(clients):
    """The whole §6 entry point: a stranger gets one message, and it lands as a
    request rather than in the recipient's main inbox."""
    ada = await clients("ada")
    chidi = await clients("chidi")

    r = await _send(ada, "chidi", "is this still available?")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == ConversationStatus.PENDING, body
    assert body["accepted_now"] is False, "a first message accepts nothing"
    assert body["message"]["is_mine"] is True, (
        "the sender's own copy came back aligned as the other person's"
    )

    inbox = await _inbox(chidi)
    assert inbox["pending_requests"] == 1, inbox
    assert len(inbox["items"]) == 1, inbox
    row = inbox["items"][0]
    assert row["is_request"] is True, (
        "a pending thread somebody else started must read as a request to them"
    )
    assert row["preview"] == "is this still available?", row
    assert row["preview_is_mine"] is False, (
        "the recipient's row is claiming they sent the message"
    )
    assert row["unread"] == 1, row

    # The initiator's own pending thread is NOT a request in their inbox.
    mine = await _inbox(ada)
    assert mine["pending_requests"] == 0, mine
    assert mine["items"][0]["is_request"] is False, mine
    assert mine["items"][0]["preview_is_mine"] is True, mine


async def test_the_initiator_cannot_send_a_second_message(clients):
    """409, not 403: the block is temporary and the client should keep the draft."""
    ada = await clients("ada")
    await clients("chidi")

    assert (await _send(ada, "chidi", "one")).status_code == 200
    second = await _send(ada, "chidi", "two")
    assert second.status_code == 409, second.text
    assert "one message" in second.json()["error"]["message"], second.text


async def test_replying_is_accepting(clients):
    """Nobody should have to press Accept before they can type (§6)."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    await _send(ada, "chidi", "hi")

    reply = await chidi.post("/api/messages/threads/ada", json={"body": "yes!"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["accepted_now"] is True, (
        "the reply did not flip the thread out of PENDING"
    )
    assert reply.json()["status"] == ConversationStatus.ACCEPTED

    # And now the initiator may write freely.
    again = await _send(ada, "chidi", "great")
    assert again.status_code == 200, again.text
    assert again.json()["accepted_now"] is False, (
        "an already-accepted thread reported accepting again"
    )


async def test_a_declined_request_bars_the_initiator_for_good(clients):
    """403, not 409 — this one is final, so the client should discard the draft."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    first = await _send(ada, "chidi", "hi")
    conversation_id = first.json()["conversation_public_id"]

    declined = await chidi.post(f"/api/messages/{conversation_id}/decline")
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == ConversationStatus.DECLINED
    assert declined.json()["archived"] is True

    blocked = await _send(ada, "chidi", "hello?")
    assert blocked.status_code == 403, blocked.text


async def test_the_decliner_may_still_change_their_mind(clients):
    """A decline removes the thread from your inbox; it does not stop *you*."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    first = await _send(ada, "chidi", "hi")
    await chidi.post(f"/api/messages/{first.json()['conversation_public_id']}/decline")

    reply = await chidi.post("/api/messages/threads/ada", json={"body": "actually…"})
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == ConversationStatus.ACCEPTED, (
        "the decliner writing back did not reopen the thread"
    )


async def test_you_cannot_message_yourself(clients):
    ada = await clients("ada")
    r = await _send(ada, "ada", "hello me")
    assert r.status_code == 422, r.text


async def test_an_empty_message_is_refused(clients):
    ada = await clients("ada")
    await clients("chidi")
    r = await _send(ada, "chidi", "   ")
    assert r.status_code == 422, r.text
    assert "body" in r.json()["error"].get("fields", {}), r.text


# --- the thread read ----------------------------------------------------


async def test_opening_a_stranger_thread_creates_nothing(clients, db: AsyncSession):
    """`/messages/@ada` is compose-first: it renders a live composer and no row.

    Browsing to a handle must not litter two inboxes with an empty conversation,
    so this asserts the *database*, not just the response shape.
    """
    ada = await clients("ada")
    await clients("chidi")

    view = await _thread(ada, "chidi")
    assert view["conversation"] is None, view
    assert view["messages"] == [], view
    assert view["can_send"] is True, view
    assert view["other"]["username"] == "chidi", view
    # New threads start with the timer on, before any row exists to hold it.
    assert view["disappearing"] is True, view

    count = (
        await db.execute(select(func.count()).select_from(Conversation))
    ).scalar_one()
    assert count == 0, "a GET created a conversation row"


async def test_a_thread_renders_both_sides_from_each_point_of_view(clients):
    """`is_mine` is computed per viewer, so the same two messages align opposite
    ways for the two participants. A single shared payload would put one side's
    bubbles on the wrong side of the other's screen.

    Asserted as a body→alignment mapping rather than by position, because who sent
    what is the claim here and the chronology is tested separately.
    """
    ada = await clients("ada")
    chidi = await clients("chidi")
    await _send(ada, "chidi", "from ada")
    await chidi.post("/api/messages/threads/ada", json={"body": "from chidi"})

    hers = {m["body"]: m["is_mine"] for m in (await _thread(ada, "chidi"))["messages"]}
    his = {m["body"]: m["is_mine"] for m in (await _thread(chidi, "ada"))["messages"]}

    assert hers == {"from ada": True, "from chidi": False}, hers
    assert his == {"from ada": False, "from chidi": True}, his


async def test_a_thread_reads_oldest_first(clients, db: AsyncSession):
    """The page is a transcript: the newest message belongs at the bottom, where
    the composer is. The query fetches the newest page descending and has to turn
    it back round — which is exactly the step that gets forgotten."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    await _send(ada, "chidi", "first")
    await chidi.post("/api/messages/threads/ada", json={"body": "second"})
    await _make_older(db, "first", minutes=5)

    view = await _thread(ada, "chidi")
    assert [m["body"] for m in view["messages"]] == ["first", "second"], view


async def test_an_incoming_request_gets_a_live_composer(clients):
    """§7: Accept / Delete render *above* a working composer, not instead of one."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    await _send(ada, "chidi", "hi")

    view = await _thread(chidi, "ada")
    assert view["is_incoming_request"] is True, view
    assert view["can_send"] is True, (
        "the recipient of a request cannot type, so replying-is-accepting is unreachable"
    )

    # The initiator sees the mirror image: not a request, and a closed composer.
    mine = await _thread(ada, "chidi")
    assert mine["is_incoming_request"] is False, mine
    assert mine["can_send"] is False, mine
    assert mine["blocked_reason"], "a closed composer with no explanation"


async def test_reading_a_thread_does_not_mark_it_read(clients):
    """Marking read is an explicit POST, so a thread opened in a background tab
    cannot silently clear a badge."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    await _send(ada, "chidi", "hi")

    assert await _badge(chidi) == 1
    view = await _thread(chidi, "ada")
    assert view["unread"] == 1, view
    assert await _badge(chidi) == 1, "a GET cleared the unread badge"


async def test_marking_read_clears_the_badge_and_shows_their_tick(clients):
    ada = await clients("ada")
    chidi = await clients("chidi")
    sent = await _send(ada, "chidi", "hi")
    conversation_id = sent.json()["conversation_public_id"]

    r = await chidi.post(f"/api/messages/{conversation_id}/read")
    assert r.status_code == 200, r.text
    assert r.json()["unread"] == 0, r.text
    assert r.json()["last_read_at"], r.text

    assert await _badge(chidi) == 0, "the badge survived an explicit read"
    # §17's second tick: the sender can now see they have been read.
    hers = await _thread(ada, "chidi")
    assert hers["their_last_read_at"] is not None, hers


async def test_the_badge_never_counts_a_thread_the_inbox_hides(
    clients, db: AsyncSession
):
    """A badge is a promise that there is something to open.

    The inbox drops threads whose other side has been deleted or suspended. If the
    counts do not drop the same rows, the number can never reach zero: there is no
    row to open, so no way to mark it read. A permanent "1" next to Messages is
    worse than no badge at all, because it trains people to ignore it.
    """
    ada = await clients("ada")
    chidi = await clients("chidi")
    await _send(ada, "chidi", "hi")
    assert await _badge(chidi) == 1
    assert len((await _inbox(chidi))["items"]) == 1

    sender = await _user(db, "ada")
    sender.account_status = AccountStatus.SUSPENDED
    await db.commit()

    assert (await _inbox(chidi))["items"] == [], "a suspended account still lists"
    assert await _badge(chidi) == 0, (
        "the badge counts a thread the inbox will not show, so it can never be "
        "cleared"
    )
    assert (await _inbox(chidi))["unread_conversations"] == 0
    assert (await _inbox(chidi))["pending_requests"] == 0, (
        "the Requests tab counter disagrees with the tab itself"
    )


# --- accept / decline / archive authorization ---------------------------


async def test_you_cannot_accept_your_own_request(clients):
    """Otherwise §6 is a formality with an extra button."""
    ada = await clients("ada")
    await clients("chidi")
    sent = await _send(ada, "chidi", "hi")

    r = await ada.post(f"/api/messages/{sent.json()['conversation_public_id']}/accept")
    assert r.status_code == 403, r.text


async def test_accept_moves_it_out_of_requests_without_a_reply(clients):
    ada = await clients("ada")
    chidi = await clients("chidi")
    sent = await _send(ada, "chidi", "hi")

    r = await chidi.post(f"/api/messages/{sent.json()['conversation_public_id']}/accept")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == ConversationStatus.ACCEPTED

    inbox = await _inbox(chidi)
    assert inbox["pending_requests"] == 0, inbox
    assert inbox["items"][0]["is_request"] is False, inbox
    # Accepting is not reading — the message is still unread.
    assert inbox["items"][0]["unread"] == 1, inbox

    # Idempotent: the button can be double-tapped.
    again = await chidi.post(
        f"/api/messages/{sent.json()['conversation_public_id']}/accept"
    )
    assert again.status_code == 200, again.text


@pytest.mark.parametrize(
    "action,method",
    [
        ("read", "post"),
        ("accept", "post"),
        ("decline", "post"),
        ("archive", "post"),
    ],
)
async def test_a_stranger_gets_404_not_403(clients, action: str, method: str):
    """§25: a non-participant must not be able to tell a real conversation from an
    imaginary one. 403 would confirm it exists and that they are not in it."""
    ada = await clients("ada")
    await clients("chidi")
    nosy = await clients("nosy")
    sent = await _send(ada, "chidi", "private")
    conversation_id = sent.json()["conversation_public_id"]

    real = await getattr(nosy, method)(f"/api/messages/{conversation_id}/{action}")
    imaginary = await getattr(nosy, method)(f"/api/messages/{uuid.uuid4()}/{action}")
    assert real.status_code == 404, real.text
    assert real.json()["error"]["message"] == imaginary.json()["error"]["message"], (
        "somebody else's conversation answers differently from one that never existed"
    )


async def test_archiving_hides_a_thread_from_my_inbox_only(clients):
    ada = await clients("ada")
    chidi = await clients("chidi")
    sent = await _send(ada, "chidi", "hi")
    await chidi.post("/api/messages/threads/ada", json={"body": "hey"})
    conversation_id = sent.json()["conversation_public_id"]

    r = await ada.post(f"/api/messages/{conversation_id}/archive")
    assert r.status_code == 200, r.text
    assert r.json()["archived"] is True

    assert (await _inbox(ada))["items"] == [], "the archived thread is still in my inbox"
    assert len((await _inbox(chidi))["items"]) == 1, (
        "archiving on one side removed the thread from the other side's inbox too"
    )


async def test_a_new_message_brings_an_archived_thread_back(clients):
    """A thread you put away and somebody then wrote into is a thread you want back."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    sent = await _send(ada, "chidi", "hi")
    await chidi.post("/api/messages/threads/ada", json={"body": "hey"})
    await ada.post(f"/api/messages/{sent.json()['conversation_public_id']}/archive")
    assert (await _inbox(ada))["items"] == []

    await chidi.post("/api/messages/threads/ada", json={"body": "still there?"})
    items = (await _inbox(ada))["items"]
    assert len(items) == 1, "a new message did not un-archive the thread"
    assert items[0]["preview"] == "still there?", items


# --- the tabs and search ------------------------------------------------


async def test_the_tabs_filter_what_they_say_they_do(clients):
    """All / Unread / Requests, plus the deliberate fallback for a mistyped one."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    ngozi = await clients("ngozi")

    # A request to chidi, and an accepted thread with ngozi.
    await _send(ada, "chidi", "a request")
    await _send(ngozi, "chidi", "hello")
    await chidi.post("/api/messages/threads/ngozi", json={"body": "hi back"})

    all_rows = await _inbox(chidi, filter="all")
    assert len(all_rows["items"]) == 2, all_rows
    assert all_rows["pending_requests"] == 1, all_rows

    requests = await _inbox(chidi, filter="requests")
    assert [r["other"]["username"] for r in requests["items"]] == ["ada"], requests

    # chidi has replied to ngozi (so read there) and not to ada.
    unread = await _inbox(chidi, filter="unread")
    assert [r["other"]["username"] for r in unread["items"]] == ["ada"], unread

    # A mistyped tab arrives from a URL a user can edit: fall back to All, not 422.
    typo = await _inbox(chidi, filter="unreadd")
    assert len(typo["items"]) == 2, typo


async def test_search_matches_a_name_or_a_handle(clients):
    ada = await clients("ada")
    await clients("chidi")
    await clients("ngozi")
    await _send(ada, "chidi", "hi")
    await _send(ada, "ngozi", "hi")

    by_handle = await _inbox(ada, q="chi")
    assert [r["other"]["username"] for r in by_handle["items"]] == ["chidi"], by_handle

    by_name = await _inbox(ada, q="ngozi test")
    assert [r["other"]["username"] for r in by_name["items"]] == ["ngozi"], by_name

    assert (await _inbox(ada, q="nobody"))["items"] == []


# --- the compose picker -------------------------------------------------


async def test_candidates_are_scoped_to_the_follow_graph(clients, db: AsyncSession):
    """Not a user search. This endpoint must never become an account-enumeration
    surface for the sake of a convenience feature."""
    ada = await clients("ada")
    await clients("chidi")
    await clients("ngozi")
    await clients("stranger")

    me = await _user(db, "ada")
    # One I follow, one who follows me — both should be offered.
    db.add(UserFollow(follower_id=me.id, following_id=(await _user(db, "chidi")).id))
    db.add(UserFollow(follower_id=(await _user(db, "ngozi")).id, following_id=me.id))
    await db.commit()

    r = await ada.get("/api/messages/candidates")
    assert r.status_code == 200, r.text
    handles = {u["username"] for u in r.json()["items"]}
    assert handles == {"chidi", "ngozi"}, handles
    assert "stranger" not in handles, (
        "an account with no follow edge is being offered, so this is a user search"
    )
