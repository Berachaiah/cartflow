"""
Blocking and reporting — §22 and §23.

Blocking is the one place in messaging where the API is required to *lie by
omission*, and every test here exists to pin down a specific shape of that:

**A block never announces itself.** Somebody who has been blocked must get the
same answer they would get for a handle that does not exist — not a special code,
not a different message, not a subtly different latency-free 403. So the tests
compare a blocked request against a nonexistent-handle request and assert the two
responses are *identical*, rather than asserting each is a 404 on its own. A 404
with the wording "you have been blocked" would pass the weaker test and break the
promise entirely.

**It works in both directions.** A block stops the blocker writing to the blocked
account as well: half a block is a trap where you can still be drawn into a
conversation with somebody you removed.

**It is a state, not a transition.** Blocking twice is a 200 with `changed: false`,
because the button promises "this person is blocked" and a double tap on a slow
connection should not produce an error.

Reporting is tested for the two properties a moderation queue depends on: an admin
is actually told, and you cannot staple somebody else's conversation id to your
report to drag an unrelated thread into moderation.
"""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.report import Report, ReportStatus

PASSWORD = "password123"


# --- helpers -------------------------------------------------------------


def _shape(response: Response) -> dict:
    """The part of an error body a caller could compare two requests on.

    Everything except `correlation_id`, which the middleware makes unique per
    request — two identical errors never have the same one, so whole-body equality
    could not hold even for two 404s that are genuinely indistinguishable. `fields`
    is left in deliberately: a validation detail that appeared for a blocked
    account and not for a stranger would be exactly the tell these tests are for.
    """
    error = dict(response.json()["error"])
    error.pop("correlation_id", None)
    return error


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
async def mail(monkeypatch):
    """Capture the admin notification instead of sending it.

    Patched at `app.services.reports.send_email` — the name the service imported —
    because patching the integration module would leave the service holding its own
    reference to the real function.
    """
    sent: list[dict] = []

    async def _capture(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.services.reports.send_email", _capture)
    return sent


async def _both_ways(a: AsyncClient, b: AsyncClient, *, a_name: str, b_name: str):
    return (
        await a.post(f"/api/messages/threads/{b_name}", json={"body": "hello"}),
        await b.post(f"/api/messages/threads/{a_name}", json={"body": "hello"}),
    )


# --- §22: blocking ------------------------------------------------------


async def test_a_block_is_indistinguishable_from_a_handle_that_never_existed(clients):
    """The core promise. Not "returns 404" — returns *the same thing*, so there is
    no signal to read."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    await chidi.post("/api/messages/blocks/ada")

    blocked = await ada.post("/api/messages/threads/chidi", json={"body": "hello?"})
    ghost = await ada.post("/api/messages/threads/nobodyhere", json={"body": "hello?"})

    assert blocked.status_code == ghost.status_code == 404, blocked.text
    assert _shape(blocked) == _shape(ghost), (
        "a blocked send answers differently from a send to a handle that does not "
        "exist, which is how somebody works out they have been blocked"
    )

    # Reading the thread tells them nothing either.
    view = await ada.get("/api/messages/threads/chidi")
    ghost_view = await ada.get("/api/messages/threads/nobodyhere")
    assert view.status_code == ghost_view.status_code == 404, view.text
    assert _shape(view) == _shape(ghost_view), view.text


async def test_a_block_stops_both_directions(clients):
    """Half a block would leave the person who blocked reachable by the person they
    blocked — and leave *them* able to start a conversation they have already said
    they do not want."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    await chidi.post("/api/messages/blocks/ada")

    outgoing, incoming = await _both_ways(ada, chidi, a_name="ada", b_name="chidi")
    assert outgoing.status_code == 404, outgoing.text
    assert incoming.status_code == 404, (
        "the blocker can still write to the person they blocked"
    )


async def test_blocking_hides_an_existing_thread_from_both_inboxes(clients):
    ada = await clients("ada")
    chidi = await clients("chidi")
    await ada.post("/api/messages/threads/chidi", json={"body": "hi"})
    await chidi.post("/api/messages/threads/ada", json={"body": "hey"})
    assert len((await ada.get("/api/messages")).json()["items"]) == 1

    await chidi.post("/api/messages/blocks/ada")

    assert (await ada.get("/api/messages")).json()["items"] == [], (
        "a blocked account can still see the thread in their inbox"
    )
    assert (await chidi.get("/api/messages")).json()["items"] == [], (
        "the blocker still has the thread in their own inbox"
    )
    # And the unread badge cannot leak it either.
    assert (await ada.get("/api/messages/unread")).json()["count"] == 0


async def test_blocking_promises_a_state_not_a_transition(clients):
    ada = await clients("ada")
    await clients("chidi")

    first = await ada.post("/api/messages/blocks/chidi")
    second = await ada.post("/api/messages/blocks/chidi")
    assert first.status_code == 200, first.text
    assert first.json() == {"blocked": True, "changed": True}, first.text
    assert second.status_code == 200, second.text
    assert second.json() == {"blocked": True, "changed": False}, second.text

    first_undo = await ada.delete("/api/messages/blocks/chidi")
    second_undo = await ada.delete("/api/messages/blocks/chidi")
    assert first_undo.json() == {"blocked": False, "changed": True}, first_undo.text
    assert second_undo.json() == {"blocked": False, "changed": False}, second_undo.text


async def test_unblocking_restores_the_thread_it_hid(clients):
    """The messages were never deleted, only made unreachable — so unblocking gives
    the conversation back rather than starting a fresh one under §6."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    sent = await ada.post("/api/messages/threads/chidi", json={"body": "hi"})
    await chidi.post("/api/messages/threads/ada", json={"body": "hey"})
    conversation_id = sent.json()["conversation_public_id"]

    await chidi.post("/api/messages/blocks/ada")
    await chidi.delete("/api/messages/blocks/ada")

    rows = (await ada.get("/api/messages")).json()["items"]
    assert [r["public_id"] for r in rows] == [conversation_id], rows
    view = await ada.get("/api/messages/threads/chidi")
    assert view.status_code == 200, view.text
    assert {m["body"] for m in view.json()["messages"]} == {"hi", "hey"}, view.text

    again = await ada.post("/api/messages/threads/chidi", json={"body": "back"})
    assert again.status_code == 200, again.text


async def test_blocking_an_unknown_handle_is_a_404(clients):
    ada = await clients("ada")
    r = await ada.post("/api/messages/blocks/nobodyhere")
    assert r.status_code == 404, r.text


async def test_you_cannot_block_yourself(clients):
    """A self-block would make the account unreachable to itself in ways nothing
    else in the app is prepared for, so it is refused rather than absorbed."""
    ada = await clients("ada")
    r = await ada.post("/api/messages/blocks/ada")
    assert r.status_code == 422, r.text


async def test_blocking_needs_a_session(clients):
    anonymous = await clients()
    r = await anonymous.post("/api/messages/blocks/ada")
    assert r.status_code == 401, r.text


# --- §23: reporting -----------------------------------------------------


async def test_a_report_reaches_a_moderator(clients, mail, db: AsyncSession):
    ada = await clients("ada")
    chidi = await clients("chidi")
    sent = await ada.post("/api/messages/threads/chidi", json={"body": "buy crypto"})

    filed = await chidi.post(
        "/api/messages/reports/ada",
        json={
            "reason": "spam",
            "note": "unsolicited",
            "conversation_public_id": sent.json()["conversation_public_id"],
        },
    )
    assert filed.status_code == 200, filed.text
    reference = filed.json()["reference"]

    assert len(mail) == 1, "a report was filed and no admin was told"
    assert reference in mail[0]["html"], (
        "the admin email does not quote the reference the reporter was given"
    )

    report = (
        await db.execute(select(Report).execution_options(populate_existing=True))
    ).scalars().one()
    assert str(report.public_id) == reference
    assert report.status == ReportStatus.OPEN
    assert report.conversation_id is not None, (
        "the thread context was dropped, so a moderator has no messages to read"
    )
    assert report.emailed_at is not None, (
        "the send succeeded but the row was not stamped as notified"
    )


async def test_a_report_without_a_thread_is_fine(clients, mail, db: AsyncSession):
    """Reporting from a profile carries no conversation, and that is a valid report
    — the context is optional, not merely unvalidated."""
    ada = await clients("ada")
    await clients("chidi")

    filed = await ada.post("/api/messages/reports/chidi", json={"reason": "abuse"})
    assert filed.status_code == 200, filed.text

    report = (
        await db.execute(select(Report).execution_options(populate_existing=True))
    ).scalars().one()
    assert report.conversation_id is None


async def test_you_cannot_attach_a_conversation_you_are_not_in(clients, mail):
    """Otherwise a report is a way to pull a stranger's thread into a moderation
    queue — and, since an invalid id would answer differently, a way to probe for
    which conversation ids exist."""
    ada = await clients("ada")
    chidi = await clients("chidi")
    nosy = await clients("nosy")
    sent = await ada.post("/api/messages/threads/chidi", json={"body": "private"})

    real = await nosy.post(
        "/api/messages/reports/ada",
        json={
            "reason": "spam",
            "conversation_public_id": sent.json()["conversation_public_id"],
        },
    )
    imaginary = await nosy.post(
        "/api/messages/reports/ada",
        json={"reason": "spam", "conversation_public_id": str(uuid.uuid4())},
    )
    assert real.status_code == 404, real.text
    assert _shape(real) == _shape(imaginary), (
        "a conversation somebody else is in answers differently from one that does "
        "not exist"
    )
    assert mail == [], "a rejected report still emailed an admin"


async def test_an_unknown_reason_is_refused(clients, mail):
    ada = await clients("ada")
    await clients("chidi")
    r = await ada.post(
        "/api/messages/reports/chidi", json={"reason": "i-just-dont-like-them"}
    )
    assert r.status_code == 422, r.text
    assert mail == []


async def test_reporting_the_same_account_twice_folds_into_one_open_report(
    clients, mail, db: AsyncSession
):
    """A moderator should see one case with a history, not two identical rows —
    and the reporter should not be able to tell the difference, because from their
    side both mean "this has been filed"."""
    ada = await clients("ada")
    await clients("chidi")

    first = await ada.post("/api/messages/reports/chidi", json={"reason": "spam"})
    second = await ada.post("/api/messages/reports/chidi", json={"reason": "spam"})
    assert first.status_code == second.status_code == 200, second.text
    assert first.json() == second.json(), (
        "the second report returned a different reference, which tells the reporter "
        "something only moderation needs to know"
    )

    reports = (
        (await db.execute(select(Report).execution_options(populate_existing=True)))
        .scalars()
        .all()
    )
    assert len(reports) == 1, f"{len(reports)} rows for one repeated report"


async def test_you_cannot_report_yourself(clients, mail):
    ada = await clients("ada")
    r = await ada.post("/api/messages/reports/ada", json={"reason": "spam"})
    assert r.status_code == 422, r.text
    assert mail == []


async def test_reporting_an_unknown_handle_is_a_404(clients, mail):
    ada = await clients("ada")
    r = await ada.post("/api/messages/reports/nobodyhere", json={"reason": "spam"})
    assert r.status_code == 404, r.text
    assert mail == []
