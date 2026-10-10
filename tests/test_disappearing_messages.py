"""
Disappearing messages — the read filter, the sweep, and the toggle.

The feature has two halves and they fail differently, so they are tested apart:

**The read filter is correctness.** A message past its `expires_at` is invisible
everywhere — thread, inbox preview, unread count — the *instant* it expires,
regardless of whether anything has swept it. That is why the first test here
asserts the message is gone from the API while its row is still verifiably in the
database: if invisibility depended on the sweep having run, a user would see a
"disappeared" message for as long as nobody happened to trigger a purge.

**The sweep is storage.** It hard-deletes the rows and destroys the photos. It can
lag by any amount without anyone noticing, which also means a broken sweep is
silent — hence tests that count rows rather than read responses.

**The timer is a snapshot, not a filter.** Each message carries the expiry it was
sent with, so turning the timer off makes new messages permanent and leaves
existing ones counting down. The alternative — recomputing from the
conversation's current setting — would let either participant retroactively
un-expire the other person's already-sent messages, which is the opposite of what
the switch promises.

One sequencing trap runs through this file: **opening a thread purges it**
(`get_thread` calls `purge_expired` for that conversation). So a test that wants
to observe an expired-but-present row has to look at the inbox or the database
*before* it opens the thread. Where that matters it is called out inline.
"""

import uuid
from datetime import datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import ensure_utc, utc_now
from app.main import app
from app.models.conversation import (
    DEFAULT_DISAPPEAR_SECONDS,
    Conversation,
    Message,
)
from app.models.report import Report, ReportStatus
from app.services import messaging as messaging_service

PASSWORD = "password123"


# --- helpers -------------------------------------------------------------


@pytest_asyncio.fixture
async def clients(client: AsyncClient):
    """Additional browsers against the same app and test DB. See test_messaging."""
    made: list[AsyncClient] = []

    async def _make(username: str | None = None) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        made.append(c)
        if username is not None:
            r = await c.post(
                "/api/auth/signup",
                json={
                    "role": "individual",
                    "full_name": f"{username.title()} Tester",
                    "username": username,
                    "email": f"{username}@example.com",
                    "password": PASSWORD,
                },
            )
            assert r.status_code == 201, r.text
            r = await c.post(
                "/api/auth/login",
                json={"identifier": username, "password": PASSWORD},
            )
            assert r.status_code == 200, r.text
        return c

    yield _make
    for c in made:
        await c.aclose()


@pytest_asyncio.fixture
async def talking(clients):
    """Two signed-in people with an ACCEPTED thread, so either may write.

    Most of this file needs more than one message in a thread, and §6 stops the
    initiator sending twice — so almost every test would otherwise open with the
    same four lines of handshake.
    """
    ada = await clients("ada")
    chidi = await clients("chidi")
    first = await ada.post("/api/messages/threads/chidi", json={"body": "opening"})
    assert first.status_code == 200, first.text
    reply = await chidi.post("/api/messages/threads/ada", json={"body": "replying"})
    assert reply.status_code == 200, reply.text
    return ada, chidi, first.json()["conversation_public_id"]


async def _conversation(db: AsyncSession, public_id) -> Conversation:
    """Fetch a conversation, ignoring anything this session has cached.

    `populate_existing` matters: the app committed through a *different* session on
    the same connection, and with `expire_on_commit=False` a plain select would
    hand back this session's stale copy from the identity map.
    """
    stmt = (
        select(Conversation)
        .where(Conversation.public_id == uuid.UUID(str(public_id)))
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _messages(db: AsyncSession, public_id) -> list[Message]:
    """Every message row in a thread, straight from the database.

    Ordered by `created_at` only — deliberately no tiebreak, because the id is a
    random UUID and sorting on it would invent a chronology that does not exist
    (see `_timeline`). Tests that need a definite order establish one first.
    """
    conversation = await _conversation(db, public_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(stmt)).scalars())


async def _timeline(db: AsyncSession, public_id, bodies: list[str]) -> None:
    """Give a thread a definite chronology, in the order `bodies` lists.

    `created_at` is `server_default=func.now()`, which on SQLite is
    `CURRENT_TIMESTAMP` — **one-second resolution**. Several messages sent by one
    test therefore share a timestamp, and every query that orders by `created_at`
    alone (the thread page, the mirror recompute) is then free to return them in
    any order. Production is PostgreSQL, where `now()` is the transaction
    timestamp and two sends are microseconds apart, so this is a harness artifact
    rather than a product bug — but a test that happens to pass because SQLite
    returned rows in insert order is a test that fails on a different machine.

    Spacing the rows a minute apart makes the chronology real, so an assertion
    about "the newest surviving message" means something.
    """
    conversation = await _conversation(db, public_id)
    rows = {m.body: m for m in await _messages(db, public_id)}
    base = utc_now() - timedelta(minutes=len(bodies) + 1)
    for offset, body in enumerate(bodies):
        assert body in rows, f"{body!r} is not in this thread: {sorted(rows)}"
        rows[body].created_at = base + timedelta(minutes=offset)
    # The mirror points at the last message sent, so it moves with it.
    conversation.last_message_at = rows[bodies[-1]].created_at
    await db.commit()


async def _backdate(
    db: AsyncSession, public_id, *, bodies: set[str] | None = None
) -> int:
    """Move message expiries into the past — the fast-forward these tests need.

    Waiting 48 hours is not an option and monkeypatching `utc_now` would only
    prove the clock can be moved, not that the queries filter on it. Rewriting
    `expires_at` exercises the real comparison against the real clock.

    `bodies` names which messages to expire, by their text, because "the newest
    one" is not a thing SQLite can tell us reliably (see `_timeline`). Omit it to
    expire everything that has a timer.

    The conversation's `last_message_expires_at` mirror is backdated alongside,
    because it is a separate column maintained by `_record_delivery` — the inbox
    reads the mirror and never the messages table, so a test that only touched the
    rows would pass while the inbox still showed the preview.
    """
    conversation = await _conversation(db, public_id)
    rows = [
        m
        for m in await _messages(db, public_id)
        if m.expires_at is not None and (bodies is None or m.body in bodies)
    ]
    if not rows:
        return 0
    past = utc_now() - timedelta(minutes=1)
    for message in rows:
        message.expires_at = past
    # Only if the message the mirror reflects is one of the ones expiring.
    if conversation.last_message_preview in {m.body for m in rows}:
        conversation.last_message_expires_at = past
    await db.commit()
    return len(rows)


async def _sweep(db: AsyncSession, *, conversation_id=None) -> int:
    """Run the purge and commit it.

    `purge_expired` leaves the transaction boundary to its caller, like every
    other service function — in the app that caller is `get_db`, which commits
    when the request succeeds. A test calling the service directly is standing in
    for the request, so it has to do the same, or the next HTTP call in the test
    reads a database where the purge never happened.
    """
    purged = await messaging_service.purge_expired(db, conversation_id=conversation_id)
    await db.commit()
    return purged


async def _inbox_row(c: AsyncClient, username: str) -> dict:
    r = await c.get("/api/messages")
    assert r.status_code == 200, r.text
    rows = [i for i in r.json()["items"] if i["other"]["username"] == username]
    assert len(rows) == 1, r.text
    return rows[0]


# --- the timer on a message ---------------------------------------------


async def test_a_message_disappears_in_48_hours_by_default(talking):
    """Nobody opts in. The thread starts with the timer on, and the number is on
    the wire so the header can label it without hard-coding 48h client-side."""
    ada, _chidi, conversation_id = talking

    sent = await ada.post("/api/messages/threads/chidi", json={"body": "with a timer"})
    assert sent.status_code == 200, sent.text
    message = sent.json()["message"]
    assert message["expires_at"] is not None, "the default is not disappearing"

    sent_at = datetime.fromisoformat(message["sent_at"])
    expires_at = datetime.fromisoformat(message["expires_at"])
    lifetime = ensure_utc(expires_at) - ensure_utc(sent_at)
    assert abs(lifetime.total_seconds() - DEFAULT_DISAPPEAR_SECONDS) < 5, (
        f"expected a ~48h lifetime, got {lifetime}"
    )

    r = await ada.get("/api/messages/threads/chidi")
    assert r.json()["disappearing"] is True, r.text
    assert r.json()["disappear_after_seconds"] == DEFAULT_DISAPPEAR_SECONDS, r.text
    # And the inbox row agrees, so the list can mark the thread as ephemeral.
    assert (await _inbox_row(ada, "chidi"))["disappearing"] is True


async def test_an_expired_message_is_invisible_before_anything_sweeps_it(
    talking, db: AsyncSession
):
    """The load-bearing property. Expiry is enforced by the read queries, so the
    message is gone from the API the moment it passes — with its row still there.

    Everything here is checked *before* any thread is opened, because opening one
    purges it and would destroy the distinction this test exists to make.
    """
    ada, chidi, conversation_id = talking
    await ada.post("/api/messages/threads/chidi", json={"body": "secret"})
    assert await _backdate(db, conversation_id) > 0

    # Still on disk: nothing has swept, and nothing needed to.
    rows = await _messages(db, conversation_id)
    assert len(rows) == 3, "the sweep ran early; this test proves nothing now"

    # Invisible anyway.
    badge = await chidi.get("/api/messages/unread")
    assert badge.json()["count"] == 0, (
        "an expired message is still counted in the unread badge"
    )

    row = await _inbox_row(chidi, "ada")
    assert row["preview"] is None, "an expired message is still previewed in the inbox"
    assert row["last_message_expired"] is True, row
    assert row["unread"] == 0, row
    assert row["preview_is_mine"] is False, (
        "a blanked preview must not claim authorship either"
    )


async def test_opening_the_thread_reclaims_the_rows(talking, db: AsyncSession):
    """The storage half. There is no scheduler yet, so the sweep rides along on
    thread-open — the moment somebody looks, the expired rows are really gone."""
    ada, chidi, conversation_id = talking
    await _backdate(db, conversation_id)

    view = await chidi.get("/api/messages/threads/ada")
    assert view.status_code == 200, view.text
    assert view.json()["messages"] == [], "expired messages came back in the thread"

    assert await _messages(db, conversation_id) == [], (
        "the thread rendered empty but the rows are still on disk"
    )
    # The mirror is recomputed, not left pointing at a deleted message.
    conversation = await _conversation(db, conversation_id)
    assert conversation.last_message_preview is None, conversation.last_message_preview
    assert conversation.last_message_expires_at is None
    assert conversation.last_message_at is None


async def test_the_conversation_survives_its_messages(talking, db: AsyncSession):
    """Disappearing messages, not disappearing conversations: the thread stays in
    both inboxes, empty, so writing again continues it rather than filing a fresh
    request under §6."""
    ada, chidi, conversation_id = talking
    await _backdate(db, conversation_id)
    await chidi.get("/api/messages/threads/ada")  # sweeps

    row = await _inbox_row(ada, "chidi")
    assert row["public_id"] == conversation_id, row
    assert row["preview"] is None, row
    assert row["status"] == "accepted", (
        "the thread was reset to pending, so the next message needs accepting again"
    )

    again = await ada.post("/api/messages/threads/chidi", json={"body": "still here"})
    assert again.status_code == 200, again.text
    assert again.json()["accepted_now"] is False, again.text


# --- the toggle ---------------------------------------------------------


async def test_turning_the_timer_off_only_affects_what_comes_next(
    talking, db: AsyncSession
):
    """Snapshot-at-send. The switch changes the future, never the past — if it
    rewrote existing messages, either participant could un-expire things the other
    person sent expecting them to vanish."""
    ada, _chidi, conversation_id = talking
    before = await _messages(db, conversation_id)
    assert all(m.expires_at is not None for m in before)

    off = await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    assert off.status_code == 200, off.text
    assert off.json()["disappearing"] is False, off.text
    assert off.json()["disappear_after_seconds"] is None, off.text
    assert off.json()["changed"] is True, off.text

    sent = await ada.post("/api/messages/threads/chidi", json={"body": "permanent"})
    assert sent.json()["message"]["expires_at"] is None, (
        "the timer is off but the new message still expires"
    )

    after = {m.body: m.expires_at for m in await _messages(db, conversation_id)}
    assert after["permanent"] is None
    assert after["opening"] is not None, (
        "turning the timer off retroactively un-expired an older message"
    )
    assert after["replying"] is not None


async def test_turning_it_back_on_resumes_for_new_messages(talking, db: AsyncSession):
    ada, chidi, conversation_id = talking
    await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    await ada.post("/api/messages/threads/chidi", json={"body": "permanent"})

    # Either participant may change it — this is a property of the thread, not of
    # whoever set it last.
    on = await chidi.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": True}
    )
    assert on.status_code == 200, on.text
    assert on.json()["disappearing"] is True, on.text
    assert on.json()["disappear_after_seconds"] == DEFAULT_DISAPPEAR_SECONDS

    sent = await chidi.post("/api/messages/threads/ada", json={"body": "ephemeral"})
    assert sent.json()["message"]["expires_at"] is not None, sent.text

    after = {m.body: m.expires_at for m in await _messages(db, conversation_id)}
    assert after["permanent"] is None, (
        "turning the timer back on retroactively expired a permanent message"
    )
    assert after["ephemeral"] is not None


async def test_the_toggle_promises_a_state_not_a_transition(talking):
    """A double tap is a 200 with `changed: False`, so a laggy connection cannot
    turn two taps into an error the user has to make sense of."""
    ada, _chidi, conversation_id = talking

    first = await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    second = await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    assert first.json()["changed"] is True, first.text
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is False, second.text
    assert second.json()["disappearing"] is False, second.text

    # Already-on is a no-op too, even though it is the default.
    again = await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": True}
    )
    assert again.json()["changed"] is True, again.text
    repeat = await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": True}
    )
    assert repeat.json()["changed"] is False, repeat.text


async def test_a_stranger_cannot_touch_the_timer(clients, talking):
    """Same 404 as a conversation that never existed (§25) — the timer is not a
    side channel for confirming two other people are talking."""
    _ada, _chidi, conversation_id = talking
    nosy = await clients("nosy")

    real = await nosy.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    imaginary = await nosy.patch(
        f"/api/messages/{uuid.uuid4()}/disappearing", json={"enabled": False}
    )
    assert real.status_code == 404, real.text
    assert real.json()["error"]["message"] == imaginary.json()["error"]["message"]


async def test_the_toggle_needs_a_bool(talking):
    ada, _chidi, conversation_id = talking
    r = await ada.patch(f"/api/messages/{conversation_id}/disappearing", json={})
    assert r.status_code == 422, r.text


# --- the sweep ----------------------------------------------------------


async def test_the_sweep_spares_a_thread_under_moderation(
    talking, db: AsyncSession, monkeypatch
):
    """§23: reporting abuse must not be the thing that destroys the evidence of it.

    A thread with an OPEN report keeps its expired rows until a moderator closes
    the report — and rejoins the sweep the moment they do.
    """
    sent_mail: list[dict] = []

    async def _capture(**kwargs):
        sent_mail.append(kwargs)

    monkeypatch.setattr("app.services.reports.send_email", _capture)

    ada, chidi, conversation_id = talking
    filed = await chidi.post(
        "/api/messages/reports/ada",
        json={
            "reason": "harassment",
            "note": "please look at this",
            "conversation_public_id": conversation_id,
        },
    )
    assert filed.status_code == 200, filed.text
    assert sent_mail, "a report was filed and no admin was told"

    await _backdate(db, conversation_id)
    purged = await _sweep(db)
    assert purged == 0, "a reported thread was swept while the report was still open"
    assert len(await _messages(db, conversation_id)) == 2

    # The messages are still invisible to both of them, though — sparing is about
    # retention for moderators, not about undoing the disappearance.
    view = await chidi.get("/api/messages/threads/ada")
    assert view.json()["messages"] == [], (
        "sparing the rows for moderation showed them to the user again"
    )

    # Moderator closes it, and the thread rejoins the next pass.
    report = (
        await db.execute(select(Report).execution_options(populate_existing=True))
    ).scalars().first()
    report.status = ReportStatus.REVIEWED
    await db.commit()

    purged = await _sweep(db)
    assert purged == 2, f"a closed report still shields the thread (purged {purged})"
    assert await _messages(db, conversation_id) == []


async def test_the_sweep_leaves_permanent_messages_alone(talking, db: AsyncSession):
    ada, chidi, conversation_id = talking
    await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    await ada.post("/api/messages/threads/chidi", json={"body": "permanent"})
    await _backdate(db, conversation_id)  # only the two older ones have a timer

    purged = await _sweep(db)
    assert purged == 2, purged
    bodies = [m.body for m in await _messages(db, conversation_id)]
    assert bodies == ["permanent"], bodies

    # And it is still readable, with the thread's preview pointing at it.
    view = await chidi.get("/api/messages/threads/ada")
    assert [m["body"] for m in view.json()["messages"]] == ["permanent"], view.text


async def test_the_preview_falls_back_to_the_newest_survivor(
    talking, db: AsyncSession
):
    """The mirror is recomputed from what is left, not just cleared — otherwise a
    thread with fifty live messages would show an empty inbox row because its most
    recent one happened to expire first."""
    ada, chidi, conversation_id = talking
    await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": False}
    )
    await ada.post("/api/messages/threads/chidi", json={"body": "keep me"})
    await ada.patch(
        f"/api/messages/{conversation_id}/disappearing", json={"enabled": True}
    )
    await chidi.post("/api/messages/threads/ada", json={"body": "drop me"})
    await _timeline(db, conversation_id, ["opening", "replying", "keep me", "drop me"])

    assert (await _inbox_row(ada, "chidi"))["preview"] == "drop me"
    assert await _backdate(db, conversation_id, bodies={"drop me"}) == 1

    assert await _sweep(db) == 1

    row = await _inbox_row(ada, "chidi")
    assert row["preview"] == "keep me", (
        "the preview did not fall back to the newest surviving message"
    )
    assert row["last_message_expired"] is False, row
    assert row["preview_is_mine"] is True, (
        "the fallback preview lost track of who sent it"
    )


async def test_the_sweep_is_scoped_when_it_is_asked_to_be(clients, db: AsyncSession):
    """Called with a conversation id — the way `get_thread` and `send_message` call
    it — the sweep must not reach into other people's threads."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    ngozi = await clients("ngozi")

    mine = await ada.post("/api/messages/threads/chidi", json={"body": "mine"})
    theirs = await ngozi.post("/api/messages/threads/chidi", json={"body": "theirs"})
    mine_id = mine.json()["conversation_public_id"]
    theirs_id = theirs.json()["conversation_public_id"]
    await _backdate(db, mine_id)
    await _backdate(db, theirs_id)

    conversation = await _conversation(db, mine_id)
    purged = await _sweep(db, conversation_id=conversation.id)
    assert purged == 1, purged
    assert await _messages(db, mine_id) == []
    assert len(await _messages(db, theirs_id)) == 1, (
        "a scoped sweep reclaimed a message from an unrelated conversation"
    )

    # An unscoped pass gets the rest — this is the call a future cron will make.
    assert await _sweep(db) == 1
    assert await _messages(db, theirs_id) == []


async def test_a_sweep_with_nothing_to_do_is_free(talking, db: AsyncSession):
    """Called on every send and every thread open, so the common case — nothing has
    expired — must return without touching anything."""
    _ada, _chidi, conversation_id = talking
    assert await _sweep(db) == 0
    assert len(await _messages(db, conversation_id)) == 2
