"""
The messaging socket — `GET /ws/messages`, upgraded.

One socket per tab, carrying everything live about messaging: incoming messages,
read receipts, typing, presence, and disappearing-timer changes. Outgoing frames
are published from wherever the event happens (`app/routers/messages.py` sends
the message and read frames); this module owns the *connection* — authenticating
it, registering it, announcing presence, and reading the two frames a client is
allowed to send.

**Auth is the session cookie, and nothing else.** A WebSocket handshake is a plain
GET, so `cartflow_session` rides along exactly as it does on every other request
and the socket authenticates the same way the REST endpoints do. What it cannot do
is use `Depends(get_current_user)`: that dependency raises `UnauthorizedError`, and
an exception handler registered on the app produces an HTTP *response*, which is
meaningless once a client is waiting for a 101. So the handshake is accepted first
and then closed with a code if the caller turns out to be anonymous — see
`_CLOSE_UNAUTHORIZED`.

**No query-string token.** The obvious alternative to a cookie is `?token=…`, and
it is a bad one: URLs are logged by proxies and load balancers in a way that
`Cookie` headers are not, so a token in the query string is a session token in
somebody's access log. `SameSite=Lax` covers the cookie for the upgrade request
(it is a top-level GET from our own origin), which is the same protection the rest
of the app relies on — the app has no CSRF token layer, deliberately, and this
must not invent one only here.

**The session is re-validated on every frame that does work.** Each handler opens
its own `session_scope()` and resolves the cookie again, so logging out (or being
suspended) closes the socket at the next frame instead of leaving a live channel
authenticated by a session that no longer exists. The cost is one indexed session
lookup per *typing* event, which is why typing is throttled.

**A socket holds no database session.** One connection can idle for hours, and a
session checked out for that long would be a pool slot lost per open tab. So there
is no `Depends(get_db)` here: every handler opens a short `session_scope()`, does
its work, commits and lets it go.

**Identifier split.** The registry routes by internal `users.id`; every frame that
crosses the wire names people by `username`. `PublicUserOut` deliberately has no
internal id (see its docstring), so a frame carrying one would be the only place
the client could learn it — and the client has no use for it, since it renders
handles. `messaging_service.handles_for` is the one bridge between the two.

Frames the client may send:

    {"type": "typing", "conversation": "<public_id>", "state": "start"|"stop"}
    {"type": "ping"}

Anything else is ignored rather than answered with an error: a frame this server
does not know is a client from a different deploy, and closing the socket over it
would turn a rolling deploy into an outage.
"""

import json
import logging
import uuid
from datetime import timedelta

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.exceptions import AppException, UnauthorizedError
from app.core.timeutils import utc_now
from app.database.session import session_scope
from app.services import messaging as messaging_service
from app.services import realtime
from app.services.session import get_current_user_from_token

logger = logging.getLogger("cartflow.ws")
settings = get_settings()

router = APIRouter(tags=["messaging"])

# 4000-4999 is the range RFC 6455 reserves for application use, so this cannot
# collide with a protocol-level code. 4401 mirrors HTTP 401 on purpose: the client
# reads it as "your session is gone, stop reconnecting and reload" rather than
# retrying with backoff the way it does after a network drop.
_CLOSE_UNAUTHORIZED = 4401

# The floor between two typing frames from one socket. Typing is the only inbound
# frame that costs a database read (the membership check), so it is also the only
# one that needs a ceiling — a client with a keystroke handler and no debounce
# would otherwise put one query on the wire per character. 1.5s is well inside the
# window a "typing…" indicator stays visible for, so throttling is invisible.
_TYPING_MIN_INTERVAL = timedelta(milliseconds=1500)


async def _publish_presence(user_ids: set[uuid.UUID], *, handle: str, online: bool) -> None:
    """Tell this user's conversation partners that they came or went.

    Sent on the first socket and the last one only (see `realtime.register` /
    `unregister`), so opening a second tab does not re-announce anything.
    """
    if not user_ids:
        return
    await realtime.publish(
        user_ids, {"type": "presence", "username": handle, "online": online}
    )


@router.websocket("/ws/messages")
async def messages_socket(websocket: WebSocket) -> None:
    """The live messaging channel for one tab.

    Accept-then-close for an anonymous caller, rather than refusing the upgrade:
    a rejected handshake reaches the browser as an opaque connection failure that
    is indistinguishable from the server being down, and the client would retry
    it forever. A close *code* is something it can read and act on.
    """
    await websocket.accept()

    raw_token = websocket.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        await websocket.close(code=_CLOSE_UNAUTHORIZED)
        return

    # The connect handshake, all in one session: who is this, stamp them as seen,
    # and work out both halves of presence — who to tell that I arrived, and who
    # is already here.
    try:
        async with session_scope() as db:
            user = await get_current_user_from_token(db, raw_token)
            user_id: uuid.UUID = user.id
            handle: str = user.username
            await messaging_service.touch_presence(db, user)
            partners = await messaging_service.partner_ids(db, viewer=user)
            # Resolved before the socket is registered so the snapshot cannot
            # contain the caller's own handle by way of a race with themselves.
            online_handles = await messaging_service.handles_for(
                db, user_ids=realtime.online_among(partners)
            )
    except UnauthorizedError:
        await websocket.close(code=_CLOSE_UNAUTHORIZED)
        return

    first_socket = realtime.register(user_id, websocket)

    try:
        # The snapshot is what stops a partner who has been connected and idle for
        # an hour from reading as offline: `last_seen_at` (which the REST payloads
        # use) is only stamped on connect, disconnect and send, so it goes stale
        # while a socket stays open. The registry is exact, and this is the client's
        # one chance to hear it without waiting for that partner to do something.
        await websocket.send_json(
            {"type": "ready", "username": handle, "online": online_handles}
        )
        if first_socket:
            await _publish_presence(partners, handle=handle, online=True)

        await _read_loop(websocket, raw_token=raw_token, user_id=user_id, handle=handle)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - a socket must not take the process with it
        logger.exception("messaging socket failed for user %s", user_id)
    finally:
        await _teardown(websocket, raw_token=raw_token, user_id=user_id, handle=handle)


async def _read_loop(
    websocket: WebSocket, *, raw_token: str, user_id: uuid.UUID, handle: str
) -> None:
    """Read frames until the peer goes away.

    `receive_text` plus `json.loads` rather than `receive_json`, because a
    malformed frame should be dropped, not raised: `receive_json` turns one bad
    payload into an exception that ends the connection, and a client that sends
    junk once is still a client whose next frame we want.
    """
    last_typing = None

    while True:
        try:
            payload = json.loads(await websocket.receive_text())
        except WebSocketDisconnect:
            raise
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            continue

        if not isinstance(payload, dict):
            continue

        kind = payload.get("type")

        if kind == "ping":
            # An application-level keepalive, separate from the protocol's own
            # ping/pong: proxies that idle out a quiet WebSocket do not always
            # count control frames, and the browser API cannot send one anyway.
            await websocket.send_json({"type": "pong"})
            continue

        if kind == "typing":
            now = utc_now()
            if last_typing is not None and now - last_typing < _TYPING_MIN_INTERVAL:
                continue
            last_typing = now
            if not await _handle_typing(
                payload, raw_token=raw_token, user_id=user_id, handle=handle
            ):
                # The session died under us. Nothing left to authenticate the
                # socket with, so close it and let the client reconnect (or
                # discover it is signed out).
                await websocket.close(code=_CLOSE_UNAUTHORIZED)
                return
            continue

        # Unknown frame: ignored, on purpose. See the module docstring.


async def _handle_typing(
    payload: dict, *, raw_token: str, user_id: uuid.UUID, handle: str
) -> bool:
    """Relay a typing indicator to the other side of one thread.

    Returns False only when the session no longer validates, which is the one
    condition the caller reacts to. Everything else — an absent or malformed
    conversation id, a thread the sender is not in, a thread that does not exist —
    is dropped silently and returns True: the checks are the same
    `require_participant` the REST endpoints use, so a socket cannot be used to
    probe for conversations, and there is nothing useful to tell a client whose
    frame was nonsense.

    Not persisted, deliberately. A typing indicator is worthless a second after it
    is sent, so it never touches the database beyond the membership check.
    """
    raw_id = payload.get("conversation")
    try:
        conversation_public_id = uuid.UUID(str(raw_id))
    except (ValueError, AttributeError, TypeError):
        return True

    # "start" unless the client explicitly says otherwise, so an older client that
    # sends a bare typing frame still lights the indicator instead of clearing it.
    state = "stop" if payload.get("state") == "stop" else "start"

    try:
        async with session_scope() as db:
            user = await get_current_user_from_token(db, raw_token)
            conversation, _ = await messaging_service.require_participant(
                db, viewer=user, public_id=conversation_public_id
            )
            audience = await messaging_service.conversation_party_ids(
                db, conversation=conversation
            )
    except UnauthorizedError:
        return False
    except AppException:
        # Not a participant, or no such conversation — a 404 on the REST side.
        return True

    # Only the far side: echoing this to the sender's own tabs would show them
    # their own "typing…".
    audience.discard(user_id)
    if audience:
        await realtime.publish(
            audience,
            {
                "type": "typing",
                "conversation": str(conversation_public_id),
                "username": handle,
                "state": state,
            },
        )
    return True


async def _teardown(
    websocket: WebSocket, *, raw_token: str, user_id: uuid.UUID, handle: str
) -> None:
    """Unregister, and announce going offline if that was the user's last socket.

    `unregister` runs first and unconditionally: it is pure in-memory bookkeeping
    that must happen even if everything after it fails, or a crashed tab would
    leave a phantom socket making its owner look permanently online.

    The rest is best-effort. Working out who to tell needs a session, and by now
    the user may have logged out — that is what closed the socket. A failure here
    costs one stale presence dot, which the partner's next inbox refresh corrects,
    so it is logged and swallowed rather than allowed to escape a `finally`.
    """
    last_socket = realtime.unregister(user_id, websocket)
    if not last_socket:
        return

    try:
        async with session_scope() as db:
            user = await get_current_user_from_token(db, raw_token)
            await messaging_service.touch_presence(db, user)
            partners = await messaging_service.partner_ids(db, viewer=user)
        await _publish_presence(partners, handle=handle, online=False)
    except Exception:  # noqa: BLE001 - see docstring
        logger.debug(
            "could not announce disconnect for user %s", user_id, exc_info=True
        )
