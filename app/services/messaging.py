"""
Messaging service — the rules doc 10 promises, in one place.

`/messages` used to render the *rules* of messaging because there were no tables
to put a thread in. This module is those rules made executable, and §6's
one-message rule is the whole reason it exists rather than the router simply
inserting rows.

**§6 as a state machine.** Every send resolves to exactly one of these:

| Conversation      | Sender     | Outcome                                    |
|-------------------|------------|--------------------------------------------|
| none yet          | anyone     | create PENDING, initiator = sender, deliver |
| PENDING           | initiator  | 409 — one message until they answer         |
| PENDING           | recipient  | deliver **and** flip to ACCEPTED            |
| ACCEPTED          | either     | deliver                                     |
| DECLINED          | initiator  | 403 — a declined request bars them for good |
| DECLINED          | recipient  | deliver and flip to ACCEPTED                |
| blocked either way| either     | 404, shaped exactly like an unknown handle  |

The two "recipient replies" rows are the same insight twice: **replying is
accepting.** A separate Accept button exists (§7) for the case where you want the
thread out of Requests without answering yet, but nobody should have to press it
before they can type.

**Following changes nothing.** §6 is explicit, and the page that shipped before
this said so to users. A stranger gets one message; someone you follow gets one
message. The only thing that opens a thread is the recipient engaging with it.

**Blocks are checked twice, on purpose.** Once in
`follow_service.resolve_public_user` (so a blocked handle cannot even be
resolved, on any surface) and once against the conversation in `send_message`
(so a thread that predates the block cannot be written into). Neither check ever
says "you are blocked" — both produce the same NotFoundError as a handle that
never existed, in both directions.

**`last_message_at` / `_preview` / `_sender_id` are written here and nowhere
else.** They are denormalised mirrors, and a denormalised column with two writers
is a bug waiting for a deadline. `_record_delivery` is the single writer.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from fastapi import UploadFile
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.core.timeutils import ensure_utc, time_ago, utc_now
from app.integrations import cloudinary_client
from app.models.conversation import (
    DEFAULT_DISAPPEAR_SECONDS,
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    Message,
    MessageKind,
    UserBlock,
    pair_key,
)
from app.models.user import User, UserFollow
from app.repositories.conversation import ConversationRepository, InboxRow
from app.services import follow as follow_service
from app.services import media as media_service

logger = logging.getLogger("cartflow.messaging")

# The longest a single message may be. Generous enough that nobody hits it in
# normal use, bounded so a 2 MB paste never reaches the database.
MAX_BODY_CHARS = 2000

# Spam ceiling: this many messages from one account per window, across every
# conversation. Per-account rather than per-thread because the abuse worth
# stopping is one account spraying twenty people, which a per-thread limit waves
# straight through. Counted by rows in a window — the same shape as
# email_verification's resend cooldown, since there is no general rate limiter.
SEND_LIMIT = 30
SEND_WINDOW = timedelta(minutes=1)

# How long after `last_seen_at` an account still reads as "Active now" (§19).
# Wide enough to cover a socket that dropped on a lift ride, short enough that it
# is not a lie.
PRESENCE_WINDOW = timedelta(minutes=5)

# What the inbox row shows for a message with no text of its own.
_PREVIEW_FALLBACKS = {
    MessageKind.IMAGE: "Sent a photo",
    MessageKind.SHARED_PRODUCT: "Shared a product",
    MessageKind.SHARED_PROFILE: "Shared a profile",
}

_MESSAGE_SUBFOLDER = "messages"


@dataclass
class ThreadView:
    """Everything one render of a thread needs, resolved in one call.

    The permission flags are computed here rather than in the template because
    they are §6, and §6 is not a presentation concern. A template asking
    "status == pending and initiator != me" would be re-deriving the state
    machine in Jinja, where it cannot be tested.
    """

    other: User
    conversation: Conversation | None = None
    messages: list[Message] = field(default_factory=list)
    # Can I type right now?
    can_send: bool = True
    # Why not, in words a user can act on. None when can_send is True.
    blocked_reason: str | None = None
    # Show the Accept / Delete / Block row: a request someone sent ME.
    is_incoming_request: bool = True
    # My own unread count in this thread before this render marked it read.
    unread: int = 0
    # When the other side last read my messages (§17). None = never opened.
    their_last_read_at: datetime | None = None
    has_more: bool = False
    # Disappearing-messages state for the header toggle. `disappearing` is whether
    # the timer is on; `disappear_after_seconds` is its value (None when off).
    # Defaults describe a thread that does not exist yet — new conversations start
    # with the 48h timer on, so the compose-first screen shows it that way before
    # the first message creates the row.
    disappearing: bool = True
    disappear_after_seconds: int | None = DEFAULT_DISAPPEAR_SECONDS


@dataclass
class InboxView:
    rows: list[InboxRow] = field(default_factory=list)
    unread_conversations: int = 0
    pending_requests: int = 0
    # Whether another page exists. Answered by over-fetching one row rather than
    # a second COUNT, and returned rather than left to the client, because the
    # client's only alternative is `len(rows) == limit` — which is wrong exactly
    # once per inbox, on the page that happens to divide evenly, and wrong in the
    # direction that offers a "load more" leading to nothing.
    has_more: bool = False


@dataclass
class SendResult:
    message: Message
    conversation: Conversation
    other: User
    # True when this send flipped PENDING/DECLINED to ACCEPTED, so the client
    # knows to move the row out of the Requests tab.
    accepted_now: bool = False


# --- presence -------------------------------------------------------------


def is_active_now(user: User | None, *, now: datetime | None = None) -> bool:
    """Whether to show "Active now" for this account.

    Reads `last_seen_at` rather than the socket registry so it is callable from
    anywhere, including a template. The registry is more precise, and
    `app/routers/ws.py` uses it directly for the live push; this is the answer
    for a page render, where a few minutes of slack is invisible.
    """
    if user is None or user.last_seen_at is None:
        return False
    reference = ensure_utc(now) if now is not None else utc_now()
    return reference - ensure_utc(user.last_seen_at) <= PRESENCE_WINDOW


def last_seen_label(user: User | None, *, now: datetime | None = None) -> str:
    """The presence line under a thread header: "Active now", "Active 2h ago", or
    "" for an account that has never been seen in a live session.

    Empty rather than "Offline" or "Last seen never": a header that announces
    absence draws attention to it, and NULL `last_seen_at` is also what every row
    that predates this feature looks like. Nothing to say, so nothing is said.
    """
    if user is None or user.last_seen_at is None:
        return ""
    if is_active_now(user, now=now):
        return "Active now"
    return f"Active {time_ago(user.last_seen_at, now=now)} ago"


async def touch_presence(db: AsyncSession, user: User) -> None:
    """Stamp `last_seen_at`. Called on socket connect/disconnect and on send —
    never per request, which would make a write of every page view."""
    user.last_seen_at = utc_now()
    await db.flush()


async def partner_ids(db: AsyncSession, *, viewer: User) -> set[uuid.UUID]:
    """The internal ids of everyone `viewer` shares a thread with — the audience
    for a presence broadcast when they connect or disconnect.

    A thin pass-through to the repository, but it exists so `app/routers/ws.py`
    can obey the layering rule the rest of the app follows: routers talk to
    services, not to repositories. `ws.py` needs this to answer "who should hear
    that I just came online", and routing that answer through the service keeps
    the one messaging query surface in one place.

    Internal ids, not handles: the realtime registry keys sockets by `user.id`
    (a UUID the client never sees), while the *frames* it sends carry `username`
    so the client can match them — the identifier split `ws.py` depends on.
    """
    return await ConversationRepository(db).partner_ids(viewer.id)


async def conversation_party_ids(
    db: AsyncSession, *, conversation: Conversation
) -> set[uuid.UUID]:
    """Both sides of one thread, by internal id — the audience for a frame about
    the conversation itself: a status flip, a read receipt, a settings change.

    Takes the `Conversation` the caller already has rather than a public id, so
    the router does not pay a second `require_participant` for something it has
    just resolved. Includes the caller: their *other* tabs need most of these
    frames too (a thread accepted on a phone should stop offering Accept on the
    laptop), and the one case where a frame must not reach the far side — a
    decline, which the initiator is deliberately never told about — is expressed
    by the router discarding an id, where that rule is visible.
    """
    return await ConversationRepository(db).participant_user_ids(conversation.id)


async def handles_for(
    db: AsyncSession, *, user_ids: Iterable[uuid.UUID]
) -> list[str]:
    """Translate internal ids to handles, for the presence snapshot a freshly
    connected socket is sent.

    The socket registry answers "who is online" in `users.id`, and the client can
    only match a handle (`PublicUserOut` has no internal id, on purpose). This is
    the bridge, and it is a service rather than a repository call in the router
    because the layering rule holds for the socket router too.
    """
    return await ConversationRepository(db).usernames_for(user_ids)


# --- helpers --------------------------------------------------------------


def _preview_for(kind: str, body: str | None) -> str:
    """The one clamped line the inbox row shows.

    Attachments fall back to a description rather than an empty string, because
    a blank row reads as a bug. Clamped to the column width here rather than
    trusting the database to truncate — Postgres would raise instead.
    """
    text = (body or "").strip().replace("\n", " ")
    if not text:
        text = _PREVIEW_FALLBACKS.get(kind, "Sent a message")
    return text[:160]


def _clean_body(body: str | None) -> str | None:
    """Trim and length-check message text. Emoji pass through untouched: the
    column is Text and both dialects store UTF-8, so nothing special is needed
    for them — which is worth stating, since it looks like an omission."""
    if body is None:
        return None
    text = body.strip()
    if not text:
        return None
    if len(text) > MAX_BODY_CHARS:
        raise ValidationAppError(
            "That message is too long.",
            fields={"body": f"Keep it under {MAX_BODY_CHARS} characters."},
        )
    return text


async def _enforce_send_limit(db: AsyncSession, sender: User) -> None:
    repo = ConversationRepository(db)
    since = utc_now() - SEND_WINDOW
    if await repo.count_messages_since(sender.id, since) >= SEND_LIMIT:
        raise RateLimitedError(
            "You're sending messages too quickly. Give it a minute and try again."
        )


async def resolve_recipient(
    db: AsyncSession, *, sender: User, username: str
) -> User:
    """The account behind a `/messages/@handle`, or a 404.

    Delegates to the follow service so a handle resolves identically everywhere —
    unknown, malformed, suspended, soft-deleted and blocked all raise the same
    NotFoundError. Self-messaging is the one case this adds: a 422, because
    unlike the others it is a mistake the client can explain rather than hide.
    """
    target = await follow_service.resolve_public_user(
        db, username=username, viewer_id=sender.id
    )
    if target.id == sender.id:
        raise ValidationAppError("You can't message yourself.")
    return target


# --- reads ----------------------------------------------------------------


async def get_inbox(
    db: AsyncSession,
    *,
    viewer: User,
    filter_name: str = "all",
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> InboxView:
    """The inbox, for one of the three tabs.

    An unrecognised `?filter=` falls back to All rather than erroring: it arrives
    from a URL a user can edit, and a 422 on a mistyped query string would be a
    worse answer than the default view.
    """
    repo = ConversationRepository(db)
    hidden = tuple(follow_service.HIDDEN_PROFILE_STATUSES)
    rows = await repo.list_inbox(
        viewer.id,
        unread_only=filter_name == "unread",
        requests_only=filter_name == "requests",
        query=query,
        hidden_statuses=hidden,
        # One more than asked for, to learn whether there is a next page without
        # paying for a COUNT over the same join. Trimmed before it leaves here.
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(rows) > limit
    return InboxView(
        rows=rows[:limit],
        unread_conversations=await repo.unread_conversation_count(
            viewer.id, hidden_statuses=hidden
        ),
        pending_requests=await repo.pending_request_count(
            viewer.id, hidden_statuses=hidden
        ),
        has_more=has_more,
    )


async def unread_count(db: AsyncSession, *, viewer: User) -> int:
    """Threads with something new — the nav badge."""
    return await ConversationRepository(db).unread_conversation_count(
        viewer.id, hidden_statuses=tuple(follow_service.HIDDEN_PROFILE_STATUSES)
    )


async def list_candidates(
    db: AsyncSession, *, viewer: User, query: str | None = None, limit: int = 20
) -> list[User]:
    """Who the compose picker offers, minus anyone blocked either way."""
    repo = ConversationRepository(db)
    excluded = await repo.blocked_or_blocking_ids(viewer.id)
    people = await repo.list_candidates(
        viewer.id,
        query=query,
        hidden_statuses=tuple(follow_service.HIDDEN_PROFILE_STATUSES),
        limit=limit + len(excluded),
    )
    return [u for u in people if u.id not in excluded][:limit]


def _send_permission(
    conversation: Conversation | None, *, viewer_id: uuid.UUID
) -> tuple[bool, str | None]:
    """Can `viewer_id` write into this conversation, and if not, why?

    The read-only half of the state-machine table above — same rows, same
    reasoning, returning copy instead of raising. `send_message` and the thread
    render must never disagree about whether the composer should work, so both
    come through here.
    """
    if conversation is None:
        return True, None

    status = conversation.status
    is_initiator = conversation.initiator_id == viewer_id

    if status == ConversationStatus.PENDING and is_initiator:
        return False, (
            "You've sent your one message. You'll be able to write again once "
            "they reply."
        )
    if status == ConversationStatus.DECLINED and is_initiator:
        return False, "This request was declined, so you can't write here."
    return True, None


async def get_thread(
    db: AsyncSession,
    *,
    viewer: User,
    username: str,
    before: datetime | None = None,
    limit: int = 30,
) -> ThreadView:
    """One thread, by the other person's handle.

    **No write happens on a GET.** Opening `/messages/@ada` for someone you have
    never written to renders an empty thread with a live composer — the row is
    created by the first POST. Otherwise browsing to a handle would litter both
    inboxes with empty conversations.
    """
    other = await resolve_recipient(db, sender=viewer, username=username)
    repo = ConversationRepository(db)

    conversation = await repo.find_between(viewer.id, other.id)
    if conversation is None:
        return ThreadView(other=other, is_incoming_request=False)

    # Reclaim this thread's expired rows and photos on open. Correctness does not
    # depend on it — the read filter below already hides anything expired — but
    # opening a thread is the other common activity signal (besides sending), so
    # doing it here means abandoned-but-browsed threads still get swept without a
    # scheduler. Self-isolating: a failure here rolls back only the purge, and the
    # thread still renders.
    await purge_expired(db, conversation_id=conversation.id)

    messages = await repo.list_messages(
        conversation.id, before=before, limit=limit + 1
    )
    has_more = len(messages) > limit
    if has_more:
        # list_messages returns oldest-first, so the surplus row is at the front.
        messages = messages[1:]

    can_send, reason = _send_permission(conversation, viewer_id=viewer.id)
    mine = await repo.get_participant(conversation.id, viewer.id)
    theirs = await repo.other_participant(conversation.id, viewer.id)

    unread = sum(
        1
        for m in messages
        if m.sender_id != viewer.id
        and (
            mine is None
            or mine.last_read_at is None
            or ensure_utc(m.created_at) > ensure_utc(mine.last_read_at)
        )
    )

    return ThreadView(
        other=other,
        conversation=conversation,
        messages=messages,
        can_send=can_send,
        blocked_reason=reason,
        is_incoming_request=(
            conversation.status == ConversationStatus.PENDING
            and conversation.initiator_id != viewer.id
        ),
        unread=unread,
        their_last_read_at=theirs.last_read_at if theirs else None,
        has_more=has_more,
        disappearing=conversation.disappear_after_seconds is not None,
        disappear_after_seconds=conversation.disappear_after_seconds,
    )


async def require_participant(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> tuple[Conversation, ConversationParticipant]:
    """Load a conversation by public id, or 404 — §25's access rule.

    A non-participant gets NotFoundError, not ForbiddenError. A 403 would confirm
    that the conversation exists and that they are not in it, which is one bit
    more than a stranger should learn about two other people.

    A block in either direction gets the same 404 (§22). Membership alone is not
    enough: both people are still participants after a block, so without this the
    thread would open, accept, archive and set its timer normally while every send
    into it 404s — and "the messages are there but nothing I do reaches them" is a
    block that has announced itself. The one 404 covers every verb that routes
    through here, so a new endpoint inherits the rule instead of having to
    remember it.
    """
    repo = ConversationRepository(db)
    conversation = await repo.get_by_public_id(public_id)
    if conversation is None:
        raise NotFoundError("That conversation doesn't exist.")

    participant = await repo.get_participant(conversation.id, viewer.id)
    if participant is None:
        raise NotFoundError("That conversation doesn't exist.")

    theirs = await repo.other_participant(conversation.id, viewer.id)
    if theirs is not None and await repo.is_blocked_between(
        viewer.id, theirs.user_id
    ):
        raise NotFoundError("That conversation doesn't exist.")
    return conversation, participant


# --- writes ---------------------------------------------------------------


async def _open_conversation(
    db: AsyncSession, *, initiator: User, other: User
) -> tuple[Conversation, bool]:
    """Create the thread and both participant rows. Returns (conversation, created).

    Under a SAVEPOINT, and re-reading on IntegrityError: two devices sending the
    first message at once would both find no conversation and both insert. The
    `uq_conversations_pair_key` constraint is what turns the loser of that race
    into an IntegrityError instead of a duplicate thread — and an IntegrityError
    raised on the OUTER transaction poisons it, so `get_db`'s commit then fails
    and the user gets a 500 for a double-tap. Same reasoning as
    `follow_service._insert_follow`, with one extra step: after losing we re-read
    the winner's row and use it, so both messages land in the same thread instead
    of one being dropped.

    `created` is False in that case, and the caller MUST re-check permission on
    it. Without that flag a double-tapped first message would slip two messages
    past §6 — the loser of the race would look like a fresh thread to a caller
    that had already decided no permission check was needed.
    """
    try:
        async with db.begin_nested():
            conversation = Conversation(
                status=ConversationStatus.PENDING,
                initiator_id=initiator.id,
                pair_key=pair_key(initiator.id, other.id),
            )
            db.add(conversation)
            await db.flush()
            db.add_all(
                [
                    ConversationParticipant(
                        conversation_id=conversation.id, user_id=initiator.id
                    ),
                    ConversationParticipant(
                        conversation_id=conversation.id, user_id=other.id
                    ),
                ]
            )
            await db.flush()
            return conversation, True
    except IntegrityError:
        existing = await ConversationRepository(db).find_between(initiator.id, other.id)
        if existing is None:
            raise
        return existing, False


async def _record_delivery(
    db: AsyncSession,
    *,
    conversation: Conversation,
    sender: User,
    kind: str,
    body: str | None = None,
    media_id: uuid.UUID | None = None,
    shared_product_slug: str | None = None,
    shared_user_id: uuid.UUID | None = None,
) -> tuple[Message, bool]:
    """Insert the message and update everything that mirrors it.

    The ONLY writer of `conversations.last_message_*`. Also the place the status
    flip lives, because "the recipient replied" and "the message was delivered"
    are one event and must not be able to half-happen.

    Un-archiving is deliberate: a thread you archived and then someone wrote into
    is a thread you want back. Only the *other* side's archive is cleared —
    clearing the sender's would resurrect a thread they chose to put away.
    """
    now = utc_now()

    # Snapshot the thread's disappearing timer onto this message. Reading it here
    # — at send time — is what gives the WhatsApp semantic: turning the timer off
    # (or changing it) governs only messages sent afterwards, because each
    # message froze its own `expires_at` and a later toggle cannot reach back. A
    # NULL timer means the thread has disappearing off, so the message is
    # permanent (expires_at stays None).
    expires_at = (
        now + timedelta(seconds=conversation.disappear_after_seconds)
        if conversation.disappear_after_seconds
        else None
    )

    message = Message(
        conversation_id=conversation.id,
        sender_id=sender.id,
        kind=kind,
        body=body,
        media_id=media_id,
        shared_product_slug=shared_product_slug,
        shared_user_id=shared_user_id,
        expires_at=expires_at,
    )
    db.add(message)

    conversation.last_message_at = now
    conversation.last_message_preview = _preview_for(kind, body)
    conversation.last_sender_id = sender.id
    # Mirror the expiry alongside the preview so the inbox can blank a row whose
    # last message has vanished without joining `messages` (see the model).
    conversation.last_message_expires_at = expires_at

    accepted_now = False
    if (
        conversation.status != ConversationStatus.ACCEPTED
        and conversation.initiator_id != sender.id
    ):
        # Replying IS accepting (§6). Also true of a DECLINED thread: the
        # recipient changing their mind is exactly what a reply means.
        conversation.status = ConversationStatus.ACCEPTED
        accepted_now = True

    repo = ConversationRepository(db)
    theirs = await repo.other_participant(conversation.id, sender.id)
    if theirs is not None:
        theirs.archived_at = None

    # The sender has, by definition, seen everything up to their own message.
    mine = await repo.get_participant(conversation.id, sender.id)
    if mine is not None:
        mine.last_read_at = now

    sender.last_seen_at = now

    await db.flush()
    return message, accepted_now


async def send_message(
    db: AsyncSession,
    *,
    sender: User,
    username: str,
    body: str | None = None,
    kind: str = MessageKind.TEXT,
    media_id: uuid.UUID | None = None,
    shared_product_slug: str | None = None,
    shared_username: str | None = None,
) -> SendResult:
    """Send a message to `username`, enforcing §6.

    One function for all four kinds, because the *rules* do not vary by kind —
    only the payload does. A photo you are not allowed to send must fail the same
    way as text you are not allowed to send, and two code paths would eventually
    disagree about that.
    """
    recipient = await resolve_recipient(db, sender=sender, username=username)
    repo = ConversationRepository(db)

    # The second block check (see the module docstring): resolve_recipient covers
    # the handle, this covers a thread that predates the block.
    if await repo.is_blocked_between(sender.id, recipient.id):
        raise NotFoundError(follow_service.PROFILE_NOT_FOUND_MESSAGE)

    body = _clean_body(body)

    shared_user_id: uuid.UUID | None = None
    if kind == MessageKind.SHARED_PROFILE:
        if not shared_username:
            raise ValidationAppError("Choose a profile to share.")
        # Resolved through the same gate: you cannot use a share card to hand
        # someone a link to an account they have blocked you from seeing.
        shared = await follow_service.resolve_public_user(
            db, username=shared_username, viewer_id=sender.id
        )
        shared_user_id = shared.id
    elif kind == MessageKind.SHARED_PRODUCT:
        if not shared_product_slug:
            raise ValidationAppError("Choose a product to share.")
    elif kind == MessageKind.IMAGE:
        if media_id is None:
            raise ValidationAppError("Choose a photo to send.")
    elif body is None:
        raise ValidationAppError(
            "Type a message first.", fields={"body": "This can't be empty."}
        )

    await _enforce_send_limit(db, sender)

    conversation = await repo.find_between(sender.id, recipient.id)
    created = False
    if conversation is None:
        conversation, created = await _open_conversation(
            db, initiator=sender, other=recipient
        )

    # Checked on any thread we did not just create — which includes the one
    # `_open_conversation` recovers after losing a create race. Gating on
    # `find_between` alone would let a double-tapped first message through:
    # both requests see no conversation, one wins, and the loser would arrive
    # here holding a PENDING thread it started with no check left to stop it.
    if not created:
        can_send, reason = _send_permission(conversation, viewer_id=sender.id)
        if not can_send:
            # 409 for "wait your turn", 403 for "you were declined". Different
            # because the first is temporary and the client should keep the draft,
            # while the second is final and it should not.
            if conversation.status == ConversationStatus.PENDING:
                raise ConflictError(reason)
            raise ForbiddenError(reason)

    message, accepted_now = await _record_delivery(
        db,
        conversation=conversation,
        sender=sender,
        kind=kind,
        body=body,
        media_id=media_id,
        shared_product_slug=shared_product_slug,
        shared_user_id=shared_user_id,
    )

    # A thread that just saw activity is the cheapest, most natural place to
    # reclaim its own expired rows and photos. Self-isolating and best-effort:
    # a purge failure can never fail the send that triggered it, and the newly
    # sent message (not yet expired) is never a candidate.
    await purge_expired(db, conversation_id=conversation.id)

    return SendResult(
        message=message,
        conversation=conversation,
        other=recipient,
        accepted_now=accepted_now,
    )


async def send_photo(
    db: AsyncSession, *, sender: User, username: str, file: UploadFile, body: str | None = None
) -> SendResult:
    """Upload a photo and send it as a message.

    Permission and the rate ceiling are checked BEFORE the upload, so a message
    you may not send never costs a Cloudinary asset. The recipient is resolved
    twice as a result (once here, once inside `send_message`) — two cheap indexed
    reads, in exchange for not uploading files that are about to be rejected.
    """
    recipient = await resolve_recipient(db, sender=sender, username=username)
    repo = ConversationRepository(db)
    conversation = await repo.find_between(sender.id, recipient.id)
    can_send, reason = _send_permission(conversation, viewer_id=sender.id)
    if not can_send:
        if conversation is not None and conversation.status == ConversationStatus.PENDING:
            raise ConflictError(reason)
        raise ForbiddenError(reason)
    await _enforce_send_limit(db, sender)

    media_service.require_media_enabled()
    data = await media_service.read_image_upload(file)
    uploaded = await media_service.upload_to_subfolder(
        data, subfolder=_MESSAGE_SUBFOLDER, filename=file.filename or "photo"
    )
    media = media_service.media_row(uploaded, owner_id=sender.id)
    db.add(media)
    await db.flush()

    return await send_message(
        db,
        sender=sender,
        username=username,
        kind=MessageKind.IMAGE,
        body=body,
        media_id=media.id,
    )


async def mark_read(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> tuple[Conversation, datetime]:
    """Move my read position to now, and return it so the other side's ticks can
    be pushed over the socket.

    The conversation comes back with it because the caller needs it to address
    that push — `require_participant` has already resolved it here, and making the
    router look it up again to find out who to tell would be two more queries for
    something this function is holding.

    Monotonic: an out-of-order request from a slow tab must not move the marker
    backwards and resurrect messages the user has already seen.
    """
    conversation, participant = await require_participant(
        db, viewer=viewer, public_id=public_id
    )
    now = utc_now()
    if participant.last_read_at is None or ensure_utc(participant.last_read_at) < now:
        participant.last_read_at = now
        await db.flush()
    return conversation, participant.last_read_at


async def accept_request(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> Conversation:
    """§7 Accept. Only the recipient may accept — the initiator accepting their
    own request would be the one-message rule with extra steps.

    Idempotent: accepting an already-accepted thread is a 200, because the button
    can be double-tapped and the end state is what was asked for.
    """
    conversation, _ = await require_participant(db, viewer=viewer, public_id=public_id)
    if conversation.initiator_id == viewer.id:
        raise ForbiddenError("You can't accept your own request.")

    if conversation.status != ConversationStatus.ACCEPTED:
        conversation.status = ConversationStatus.ACCEPTED
        await db.flush()
    return conversation


async def decline_request(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> Conversation:
    """§7 Delete. The row survives as DECLINED rather than being deleted, because
    §6 says a declined request bars the sender from writing again — a deleted row
    would let them start over, which is the opposite of what the button promises.

    The thread is archived on the decliner's side, so it leaves their inbox. The
    initiator still sees it, unchanged: telling them it was declined would make
    Delete an unwanted conversation with someone.
    """
    conversation, participant = await require_participant(
        db, viewer=viewer, public_id=public_id
    )
    if conversation.initiator_id == viewer.id:
        raise ForbiddenError("You can't decline your own request.")

    conversation.status = ConversationStatus.DECLINED
    participant.archived_at = utc_now()
    await db.flush()
    return conversation


async def archive_conversation(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> Conversation:
    """Hide a thread from MY inbox. Per-side, so the other person sees nothing
    change, and undone automatically when they next write."""
    conversation, participant = await require_participant(
        db, viewer=viewer, public_id=public_id
    )
    participant.archived_at = utc_now()
    await db.flush()
    return conversation


# --- disappearing messages -----------------------------------------------


async def set_disappearing(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID, enabled: bool
) -> tuple[Conversation, bool]:
    """Turn this thread's disappearing timer on (48h) or off. Returns the
    conversation and whether this call actually changed it.

    Either participant may toggle it — the same shared-setting model WhatsApp
    uses — so this only needs `require_participant`, not an initiator check. The
    change is stored on the conversation and read at *send* time, so it governs
    only messages sent afterwards: flipping it off does not resurrect messages
    that already expired, and flipping it on does not put a clock on messages
    already sent. Idempotent: setting the state it is already in is a no-op 200,
    which is what the second element of the return reports — computed here rather
    than by the caller reading the state first, which would be this function's
    `require_participant` all over again.

    Only 48h and off exist in V1; the column holds seconds so a future "pick a
    duration" is a value change here, not a migration.
    """
    conversation, _ = await require_participant(db, viewer=viewer, public_id=public_id)
    was_enabled = conversation.disappear_after_seconds is not None
    conversation.disappear_after_seconds = DEFAULT_DISAPPEAR_SECONDS if enabled else None
    await db.flush()
    return conversation, was_enabled != enabled


async def _recompute_last_message(
    db: AsyncSession, repo: ConversationRepository, conversation_id: uuid.UUID, now: datetime
) -> None:
    """Repoint a conversation's `last_message_*` mirror at its newest surviving
    message after a purge removed rows — or clear it to NULL if none remain.

    The mirror is the only place the inbox reads a preview from, so a purge that
    deleted the message it pointed at would otherwise leave the row showing text
    that no longer exists. Keeps `_record_delivery`'s invariant (the mirror
    reflects the newest visible message) true across deletion, not just insertion.
    """
    conversation = await repo.get(conversation_id)
    if conversation is None:
        return
    newest = await repo.newest_visible_message(conversation_id, now)
    if newest is None:
        conversation.last_message_at = None
        conversation.last_message_preview = None
        conversation.last_sender_id = None
        conversation.last_message_expires_at = None
    else:
        conversation.last_message_at = newest.created_at
        conversation.last_message_preview = _preview_for(newest.kind, newest.body)
        conversation.last_sender_id = newest.sender_id
        conversation.last_message_expires_at = newest.expires_at


async def purge_expired(
    db: AsyncSession, *, conversation_id: uuid.UUID | None = None
) -> int:
    """Reclaim storage for disappeared messages. Returns how many were purged.

    This is the *storage* half of disappearing messages; the read filter in the
    repository is the *correctness* half. A message is invisible the instant its
    `expires_at` passes regardless of this sweep — so this never has to run on any
    schedule to be correct. What it does is hard-delete those rows and destroy
    their Cloudinary photos, so a disappeared conversation stops costing anything.

    **Threads with an OPEN report are spared.** A message under active moderation
    survives until a moderator closes the report; otherwise reporting abuse would
    destroy the evidence of it (§23). Once the report is REVIEWED the thread
    rejoins the next sweep.

    Two properties make it safe to call opportunistically — it runs on every send
    and every thread open, scoped to that one conversation, and there is no
    background scheduler yet (a future cron calls it with `conversation_id=None`
    for a whole-table pass):

    * **DB work is isolated in a SAVEPOINT.** A failure mid-purge rolls back only
      the purge, never the send or the page render that triggered it — the
      caller's transaction is left clean and the operation simply reclaims
      nothing this time.
    * **Cloudinary destroys run after the commit boundary, best-effort.** They are
      network calls; holding a savepoint open across them would be a way for a
      slow provider to stall a send. A failed destroy only leaks one remote asset
      (logged), exactly the tolerance the avatar-replacement path already accepts.
    """
    repo = ConversationRepository(db)
    now = utc_now()
    cloud_ids: list[str] = []
    purged = 0

    try:
        async with db.begin_nested():
            expired = await repo.list_expired_messages(now, conversation_id=conversation_id)
            if not expired:
                return 0
            # Only pay for the open-reports lookup once something has actually
            # expired — the common case is that nothing has.
            spare = await repo.conversations_with_open_reports()
            if spare:
                expired = [m for m in expired if m.conversation_id not in spare]
            if not expired:
                return 0

            cloud_ids = [
                m.media.public_id
                for m in expired
                if m.media is not None and m.media.public_id
            ]
            media_ids = [m.media_id for m in expired if m.media_id is not None]
            message_ids = [m.id for m in expired]
            affected = {m.conversation_id for m in expired}

            await repo.delete_messages(message_ids)
            await repo.delete_media(media_ids)
            for cid in affected:
                await _recompute_last_message(db, repo, cid, now)
            purged = len(message_ids)
    except Exception:  # noqa: BLE001 - reclamation must never break its caller
        logger.exception("purge_expired failed (conversation_id=%s)", conversation_id)
        return 0

    for public_id in cloud_ids:
        try:
            await cloudinary_client.destroy(public_id)
        except Exception:  # noqa: BLE001 - best-effort; a leaked asset is logged, not fatal
            logger.warning(
                "purge_expired: could not destroy media %s", public_id, exc_info=True
            )

    return purged


# --- blocking (§22) -------------------------------------------------------


async def block_user(db: AsyncSession, *, blocker: User, username: str) -> bool:
    """Block `username`. Returns whether a row was created.

    Resolved WITHOUT the viewer's block check — deliberately. Passing `viewer_id`
    would make blocking someone twice raise a 404, and `resolve_public_user`'s
    block branch exists to hide accounts from a blocked user, not to stop the
    blocker acting on their own list.

    Blocking severs the follow edges in both directions. Leaving them would keep
    someone you cannot see in your follower count, and keep their posts eligible
    for a feed that will never be allowed to link back to them.
    """
    target = await follow_service.resolve_public_user(db, username=username)
    if target.id == blocker.id:
        raise ValidationAppError("You can't block yourself.")

    await db.execute(
        delete(UserFollow).where(
            UserFollow.follower_id.in_([blocker.id, target.id]),
            UserFollow.following_id.in_([blocker.id, target.id]),
        )
    )

    try:
        async with db.begin_nested():
            db.add(UserBlock(blocker_id=blocker.id, blocked_id=target.id))
            await db.flush()
    except IntegrityError:
        await db.flush()
        return False

    await db.flush()
    return True


async def unblock_user(db: AsyncSession, *, blocker: User, username: str) -> bool:
    """Unblock `username`. Idempotent — unblocking someone who isn't blocked is a
    no-op 200, matching how unfollow behaves. Does NOT restore the follows that
    blocking removed: those were a decision, and undoing a block is not a request
    to follow anyone again."""
    target = await follow_service.resolve_public_user(db, username=username)
    result = await db.execute(
        delete(UserBlock).where(
            UserBlock.blocker_id == blocker.id, UserBlock.blocked_id == target.id
        )
    )
    await db.flush()
    return bool(result.rowcount)


async def is_blocked_by_viewer(
    db: AsyncSession, *, viewer: User, other_id: uuid.UUID
) -> bool:
    """Has the viewer blocked this person? For rendering Block vs Unblock — the
    directional question, unlike `is_blocked_between`'s symmetric one."""
    return (
        await ConversationRepository(db).get_block(viewer.id, other_id)
    ) is not None
