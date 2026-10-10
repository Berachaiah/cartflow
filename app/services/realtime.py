"""
Realtime transport — the WebSocket registry and fan-out, and nothing else.

Live delivery lives here, deliberately *below* the routers and deliberately
*not* inside `messaging.py`. Two forces put it in its own module:

**A router may not import another router.** `messages.py` has to push a message
onto the recipient's socket the instant it is delivered, and `ws.py` owns the
sockets. If the send endpoint reached into the ws router, the layering rule the
rest of the app follows — routers depend on services, never on each other —
would have its one exception, and exceptions to that rule are how import cycles
start. So the registry is a service, and both routers depend on it.

**It cannot fold into `messaging.py`.** `messaging.py` is imported by
`schemas/message.py` (for `is_active_now` / `last_seen_label`), which is imported
by the routers that publish. If `messaging.py` also published, it would import
this module, and this module — to build a payload — would import
`schemas/message.py`: a cycle. The way out is that **this module never builds a
payload.** It moves dicts. The router, which already holds the schema, serialises
`MessageOut` (or a presence / typing / read frame) and hands the finished dict
here. So there is no schema import in this file, and no cycle to close.

**No database, no policy.** Presence *rules* (who may hear that you are online,
the five-minute grace window) live in `messaging.py` and are resolved by `ws.py`
against a real session — the partner set comes from
`ConversationRepository.partner_ids`. This module only answers "which sockets
does user X have open right now" and "send this dict to these users". Keeping it
that thin is what lets it be a module-level singleton with no lifecycle of its
own: nothing to start on boot, nothing to dispose on shutdown, and a process
restart simply empties it — every client reconnects and re-fetches on `open`.
"""

import logging
import uuid
from collections import defaultdict
from typing import Any, Iterable

from fastapi import WebSocket

logger = logging.getLogger("cartflow.realtime")

# user_id -> the sockets that user currently has open, one per tab or device.
#
# A plain dict mutated straight from the event loop: every function here runs on
# the single asyncio loop and never awaits between reading the registry and
# mutating it, so two coroutines cannot interleave a half-update. The only awaits
# are the `send_json` calls in `publish`, which iterate a *snapshot* taken before
# the first await (see there). So no lock is needed — and a lock held across an
# `await send_json` would be a way for one slow client to stall delivery to
# everyone else, which is the opposite of what a live layer is for.
_connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)


def register(user_id: uuid.UUID, websocket: WebSocket) -> bool:
    """Record an open socket. Returns True if this is the user's *first* socket.

    That flag is the signal `ws.py` uses to broadcast "now active" to this user's
    partners exactly once — on the first tab — rather than re-announcing presence
    every time they open another tab or their phone reconnects.
    """
    was_offline = not _connections[user_id]
    _connections[user_id].add(websocket)
    return was_offline


def unregister(user_id: uuid.UUID, websocket: WebSocket) -> bool:
    """Drop a closed socket. Returns True if that was the user's *last* socket.

    True is when `ws.py` broadcasts "went offline". The now-empty set is deleted
    rather than left behind, so the registry holds a key only for users who are
    actually connected, not one for everyone who has ever connected this process.
    """
    sockets = _connections.get(user_id)
    if not sockets:
        return False
    sockets.discard(websocket)
    if not sockets:
        del _connections[user_id]
        return True
    return False


def is_online(user_id: uuid.UUID) -> bool:
    """Whether this user has at least one live socket right now.

    This is the *precise* presence signal; `messaging.is_active_now` is the fuzzy
    `last_seen_at`-based one used for page renders. They can briefly disagree — a
    socket that dropped without a clean close still sits inside `last_seen_at`'s
    five-minute window — and that is the intended split: the page render is
    generous, the live dot is exact.
    """
    return bool(_connections.get(user_id))


def online_among(user_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these users are online — for the presence snapshot a freshly
    connected client is sent, so partners who are *already* online light up
    immediately instead of waiting for their next message or typing event."""
    return {uid for uid in user_ids if _connections.get(uid)}


async def publish(user_ids: Iterable[uuid.UUID], event: dict[str, Any]) -> None:
    """Send one JSON frame to every socket of every listed user.

    `user_ids` is typically ``{sender, recipient}``: the sender's own tabs get
    the frame too, which is how a second tab stays in sync — and why the client
    dedupes by `public_id`, since the sending tab also appended the message
    optimistically. A dead socket (peer gone without a close handshake) raises on
    send and is pruned here, so a crashed client is cleaned up at the next
    fan-out that touches it rather than lingering forever.
    """
    # Snapshot (user_id, socket) pairs before the first await: `publish` awaits
    # on every send, and a disconnect handler running in between mutates
    # `_connections` — iterating the live sets would risk "set changed size
    # during iteration". Deduped by socket identity so a socket registered under
    # two of the ids (a group thread, later) is not sent the same frame twice.
    targets: list[tuple[uuid.UUID, WebSocket]] = []
    seen: set[int] = set()
    for user_id in set(user_ids):
        for websocket in tuple(_connections.get(user_id, ())):
            if id(websocket) not in seen:
                seen.add(id(websocket))
                targets.append((user_id, websocket))

    for user_id, websocket in targets:
        try:
            await websocket.send_json(event)
        except Exception:  # noqa: BLE001 - any send failure means the peer is gone
            # One dead socket must not abort delivery to the rest, so this is
            # caught per-socket rather than around the loop. Pruned immediately;
            # the disconnect handler may also run, but `unregister` is idempotent.
            logger.debug("dropping dead socket for user %s", user_id, exc_info=True)
            unregister(user_id, websocket)
