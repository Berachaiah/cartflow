"""
Messaging payloads — what the wire carries for the inbox, a thread, and a send.

Three shaping decisions, because each one is the kind of thing a reader would
otherwise assume was an accident:

**Every account in here is a `PublicUserOut`.** Not a hand-built dict of "just
the fields the inbox needs" — the followers list learned that lesson already
(see `PublicUserOut`'s own docstring). One audited definition of what leaves the
server about somebody else, reused, means a new field can't leak into messaging
because messaging built its own shape.

**Timestamps ship twice: the raw instant and the server's own label.** `sent_at`
is ISO-8601 for ordering, de-duplicating and `<time datetime=…>`; `time_label` is
`timeutils.time_ago` already rendered. That looks redundant until you notice the
inbox is rendered server-side by Jinja and new messages arrive client-side over a
socket: if the browser formatted its own labels, the same thread would show one
app's "2h" above another's, and `absolute_time`'s docstring is explicit that the
app has no per-user timezone to format in. One formatter, on the server.

**Nothing here reports a block.** `can_send` plus `blocked_reason` carry why a
composer is closed, and `blocked_reason` is None in exactly the case where the
truthful answer would be "they blocked you" — that thread 404s before it can
reach a response model at all (§22).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.timeutils import absolute_time, ensure_utc, time_ago, utc_now
from app.models.conversation import ConversationStatus, MessageKind
from app.models.report import REPORT_REASONS
from app.schemas.user import PublicUserOut
from app.services import media as media_service
from app.services.messaging import is_active_now, last_seen_label

# --- outbound -------------------------------------------------------------


class MessageOut(BaseModel):
    """One bubble.

    `is_mine` is computed against the viewer rather than left to the client to
    work out from `sender_username`: the client would have to know its own handle
    to align a bubble, and a comparison it gets wrong is a message shown on the
    wrong side of the thread.
    """

    model_config = ConfigDict(from_attributes=True)

    public_id: uuid.UUID
    kind: str = MessageKind.TEXT
    body: str | None = None
    is_mine: bool = False
    sent_at: datetime
    time_label: str = ""
    exact_time: str = ""
    # When this bubble disappears, or null if it never does. The server already
    # withholds messages that have expired; this is for the ones that will expire
    # *while the thread is open*, so the client can show the countdown and drop
    # the bubble at the moment rather than only on the next reload.
    expires_at: datetime | None = None

    # --- attachments, at most one of the three (see Message's columns) ---
    # A ready-to-render URL, like PublicUserOut.avatar_url: the client never
    # learns the provider or how a derivative is built. None on an IMAGE message
    # means the media row was purged — the bubble stays, as a record that
    # something was sent, and renders a placeholder.
    image_url: str | None = None
    shared_product_slug: str | None = None
    offer_price: int | None = None
    offer_listed: int | None = None
    offer_status: str | None = None
    # None on a SHARED_PROFILE message means the account is gone (the FK is
    # ON DELETE SET NULL), and the card renders "no longer available" rather
    # than linking to a 404.
    shared_user: PublicUserOut | None = None

    # --- quoted reply (resolved for THIS viewer) -----------------------
    # `reply_is_mine` is computed server-side for the same reason `is_mine` is:
    # the client would have to know its own id to align the quote, and getting
    # that wrong shows the quote attributed to the wrong side.
    reply_public_id: uuid.UUID | None = None
    reply_body: str | None = None
    reply_is_mine: bool = False
    # True when the quoted message was deleted after this reply was sent. The
    # quote then renders "This message was deleted" instead of vanishing — a
    # reply that silently loses its context reads like a bug.
    reply_deleted: bool = False
    # [{"emoji": "❤️", "count": 2, "mine": true}] — grouped, because two people
    # reacting with the same emoji is one chip with a count, not two chips.
    reactions: list[dict] = []

    @classmethod
    def from_message(cls, message, *, viewer_id: uuid.UUID) -> "MessageOut":
        """Build from a `Message` ORM row, from the viewer's point of view.

        A classmethod rather than a helper in the router because two callers need
        it and must not diverge: the REST thread response and the WebSocket push
        (`app/routers/ws.py`) render the same bubble, and a message that looked
        different depending on whether it arrived live or on reload would be a
        very confusing bug to chase.

        Reads `message.media`, `message.shared_user` and `message.reply_to`
        (lazy="joined") plus `message.reactions` (lazy="selectin") — do not call
        this on a Message loaded by a query that defers them, or the attribute
        access raises MissingGreenlet mid-request.
        """
        reply = getattr(message, "reply_to", None)
        return cls(
            public_id=message.public_id,
            kind=message.kind,
            body=message.body,
            is_mine=message.sender_id == viewer_id,
            sent_at=message.created_at,
            time_label=time_ago(message.created_at),
            exact_time=absolute_time(message.created_at),
            expires_at=message.expires_at,
            image_url=media_service.photo_url(getattr(message, "media", None)),
            shared_product_slug=message.shared_product_slug,
            offer_price=message.offer_price,
            offer_listed=message.offer_listed,
            offer_status=message.offer_status,
            shared_user=(
                PublicUserOut.from_user(message.shared_user)
                if getattr(message, "shared_user", None) is not None
                else None
            ),
            reply_public_id=(reply.public_id if reply is not None else None),
            reply_body=(None if (reply is None or reply.deleted_at) else reply.body),
            reply_is_mine=(reply is not None and reply.sender_id == viewer_id),
            reply_deleted=bool(reply is not None and reply.deleted_at),
            reactions=_group_reactions(getattr(message, "reactions", None), viewer_id),
        )


def _group_reactions(rows, viewer_id: uuid.UUID) -> list[dict]:
    """Collapse (emoji, user) rows into one chip per emoji.

    Ordering is by first reaction so the row does not reshuffle under the
    cursor when someone reacts while you are reading.
    """
    grouped: dict[str, dict] = {}
    for row in rows or []:
        entry = grouped.setdefault(row.emoji, {"emoji": row.emoji, "count": 0, "mine": False})
        entry["count"] += 1
        if row.user_id == viewer_id:
            entry["mine"] = True
    return list(grouped.values())


class ConversationRowOut(BaseModel):
    """One inbox row.

    `preview` is the denormalised `last_message_preview`, and `preview_is_mine`
    is what lets the row read "You: …" without the client joining anything. Both
    come from `conversations`, not from the messages table — see that model's
    docstring for why those columns exist at all.
    """

    public_id: uuid.UUID
    other: PublicUserOut
    status: str
    preview: str | None = None
    preview_is_mine: bool = False
    last_message_at: datetime | None = None
    time_label: str = ""
    unread: int = 0
    # A request *to me* — pending, and I did not start it. The initiator's own
    # pending thread is not a request in their inbox, so this is False for them.
    is_request: bool = False
    is_active_now: bool = False
    # Whether this thread's disappearing timer is on — drives the header toggle
    # and lets the inbox mark a thread as ephemeral.
    disappearing: bool = True
    # The mirrored last message has expired but the sweep has not reclaimed it
    # yet (it runs on send / thread-open, not on every inbox load). The preview is
    # blanked when this is True, so a vanished message never shows in the list.
    last_message_expired: bool = False

    @classmethod
    def build(
        cls,
        *,
        conversation,
        other,
        viewer_id: uuid.UUID,
        unread: int,
        is_request: bool,
    ) -> "ConversationRowOut":
        """The single assembler for an inbox row, used by both `from_row` (the
        inbox query) and `ThreadResponse.from_view` (the thread header), so the
        two can never disagree about a row's preview, presence, or disappearing
        state.

        The expiry check is the read-filter applied to the denormalised mirror:
        if the last message has passed its `expires_at`, the preview is blanked
        here rather than trusted, because the inbox does not purge per row and the
        mirror can lag a vanished message until that thread is next opened.
        """
        expired = (
            conversation.last_message_expires_at is not None
            and ensure_utc(conversation.last_message_expires_at) <= utc_now()
        )
        return cls(
            public_id=conversation.public_id,
            other=PublicUserOut.from_user(other),
            status=conversation.status,
            preview=None if expired else conversation.last_message_preview,
            preview_is_mine=(
                False if expired else conversation.last_sender_id == viewer_id
            ),
            last_message_at=conversation.last_message_at,
            time_label=time_ago(conversation.last_message_at),
            unread=unread,
            is_request=is_request,
            is_active_now=is_active_now(other),
            disappearing=conversation.disappear_after_seconds is not None,
            last_message_expired=expired,
        )

    @classmethod
    def from_row(cls, row, *, viewer_id: uuid.UUID) -> "ConversationRowOut":
        """Build from a `ConversationRepository.InboxRow`.

        `is_request` is recomputed from (status, initiator) rather than trusted
        from the query that produced the row, so a row fetched by the All tab and
        the same row fetched by Requests agree about what it is.
        """
        conversation = row.conversation
        return cls.build(
            conversation=conversation,
            other=row.other,
            viewer_id=viewer_id,
            unread=row.unread,
            is_request=(
                conversation.status == ConversationStatus.PENDING
                and conversation.initiator_id != viewer_id
            ),
        )


class InboxResponse(BaseModel):
    """The inbox, plus the two counts the tabs and the nav badge render.

    The counts are returned with every page because they are cheap (two indexed
    counts) and because a client that tracked them locally would drift the moment
    a second tab marked something read.
    """

    items: list[ConversationRowOut]
    unread_conversations: int = 0
    pending_requests: int = 0
    # Whether `?offset=` has anything left to give. Authoritative — the client is
    # not meant to infer it from `len(items) == limit`, which is wrong on the page
    # that divides evenly and offers a "load more" that finds nothing.
    has_more: bool = False


class UnreadResponse(BaseModel):
    """Just the badge. Its own endpoint so the nav can poll or refresh it without
    pulling the whole inbox down."""

    count: int = 0


class CandidatesResponse(BaseModel):
    """The compose picker. Scoped to the follow graph in the repository — this is
    not a user search endpoint, and deliberately cannot be used as one."""

    items: list[PublicUserOut]


class ThreadResponse(BaseModel):
    """A thread, or the empty state for a conversation that does not exist yet.

    `conversation` is None for someone you have never messaged: `/messages/@ada`
    does not create a row (the first POST does), so there is genuinely nothing to
    identify yet. The client still gets `other` and `can_send`, which is
    everything the compose-first screen needs.
    """

    other: PublicUserOut
    conversation: ConversationRowOut | None = None
    messages: list[MessageOut] = Field(default_factory=list)

    can_send: bool = True
    # Why the composer is closed, in words meant for a user. None when it is open
    # — and also None for a block, which never gets this far (see module docstring).
    blocked_reason: str | None = None
    # I am looking at a pending request somebody sent me: show Accept / Delete /
    # Block / Report *above* a live composer, because replying is accepting.
    is_incoming_request: bool = False

    unread: int = 0
    # The other side's read position — §17's second tick. Null means they have
    # never opened the thread.
    their_last_read_at: datetime | None = None
    is_active_now: bool = False
    last_seen_label: str = ""
    # There is an older page behind the one returned. Drives "load earlier"
    # rather than the client guessing from `len(messages) == limit`, which is
    # wrong exactly when the count divides evenly.
    has_more: bool = False
    # Disappearing-messages state for the header toggle. `disappearing` is whether
    # the 48h timer is on; `disappear_after_seconds` is its value (null when off),
    # sent so the header can label the timer without hard-coding "48h" client-side.
    disappearing: bool = True
    disappear_after_seconds: int | None = None

    @classmethod
    def from_view(cls, view, *, viewer_id: uuid.UUID) -> "ThreadResponse":
        """Build from a `messaging_service.ThreadView`.

        The conversation row is projected through `ConversationRowOut.build` —
        the same assembler the inbox uses — so the thread header and the inbox row
        it came from cannot disagree about status, presence, or disappearing
        state. `build` wants the unread count and the request flag, which the view
        already carries.
        """
        conversation = None
        if view.conversation is not None:
            conversation = ConversationRowOut.build(
                conversation=view.conversation,
                other=view.other,
                viewer_id=viewer_id,
                unread=view.unread,
                is_request=view.is_incoming_request,
            )

        return cls(
            other=PublicUserOut.from_user(view.other),
            conversation=conversation,
            messages=[
                MessageOut.from_message(m, viewer_id=viewer_id) for m in view.messages
            ],
            can_send=view.can_send,
            blocked_reason=view.blocked_reason,
            is_incoming_request=view.is_incoming_request,
            unread=view.unread,
            their_last_read_at=view.their_last_read_at,
            is_active_now=is_active_now(view.other),
            last_seen_label=last_seen_label(view.other),
            has_more=view.has_more,
            disappearing=view.disappearing,
            disappear_after_seconds=view.disappear_after_seconds,
        )


class SendMessageResponse(BaseModel):
    """The delivered message, plus what the send did to the conversation.

    `accepted_now` is the interesting one: True when this send flipped a pending
    or declined thread to accepted, which is how the client knows to move the row
    out of Requests without re-fetching the inbox.
    """

    message: MessageOut
    conversation_public_id: uuid.UUID
    status: str
    accepted_now: bool = False

    @classmethod
    def from_result(cls, result, *, viewer_id: uuid.UUID) -> "SendMessageResponse":
        """Build from a `messaging_service.SendResult`."""
        return cls(
            message=MessageOut.from_message(result.message, viewer_id=viewer_id),
            conversation_public_id=result.conversation.public_id,
            status=result.conversation.status,
            accepted_now=result.accepted_now,
        )


class ReadResponse(BaseModel):
    """Where the viewer's read position now sits. Monotonic server-side, so a
    late request from a stale tab cannot move it backwards."""

    last_read_at: datetime
    unread: int = 0


class ConversationStateResponse(BaseModel):
    """Result of accept / decline / archive. Returns the resulting status rather
    than 204, so a client that has drifted re-syncs from the response instead of
    assuming its optimistic update was right."""

    public_id: uuid.UUID
    status: str
    archived: bool = False


class DisappearingResponse(BaseModel):
    """Result of the disappearing-messages toggle. Returns the resulting state,
    not 204, for the same reason the accept/decline responses do — a client that
    optimistically flipped the switch re-syncs from the truth. `changed` is False
    when the call set the state it was already in (a double tap is a 200), same
    contract as `BlockResponse`.

    `disappear_after_seconds` rides along so the header can relabel the timer
    ("On · 48h") from the server's number rather than assuming it, which is what
    keeps a future "choose a duration" from needing a client change here.
    """

    public_id: uuid.UUID
    disappearing: bool
    disappear_after_seconds: int | None = None
    changed: bool = True


class BlockResponse(BaseModel):
    """`blocked` is the end state; `changed` is False when the call was a no-op.
    Same contract as `FollowResponse` — the toggle promises a state, not a
    transition, so a double tap is a 200."""

    blocked: bool
    changed: bool = True


class ReportResponse(BaseModel):
    """A reference the user can quote if they follow up, and nothing else.

    Deliberately does not say whether the row was newly created or folded into an
    existing open report: from the reporter's side both mean "this has been
    filed", and the distinction is only ever moderation's business.
    """

    reference: uuid.UUID


# --- inbound --------------------------------------------------------------


class SendMessageRequest(BaseModel):
    """A send. Which fields matter depends on `kind`, and the service — not this
    schema — decides that: a missing photo and a missing product slug should fail
    with the same wording as an empty message, and `ValidationAppError` already
    produces the per-field shape every form in the app renders.

    `body` has no max_length here for the same reason. The 2000-char ceiling is
    `messaging_service.MAX_BODY_CHARS`, applied after whitespace is stripped, and
    duplicating the number in a validator is how the two end up disagreeing.
    """

    kind: str = MessageKind.TEXT
    body: str | None = None
    shared_product_slug: str | None = None
    shared_username: str | None = None
    # The quoted message, by its public id. The service resolves it against this
    # conversation, so a crafted id from another thread is rejected rather than
    # quoted.
    reply_to: uuid.UUID | None = None


class ReactionRequest(BaseModel):
    """One emoji toggle. Validated against an allowlist in the service, not here:
    the set belongs beside the reaction bar it mirrors, not in the transport
    schema."""

    emoji: str


class DisappearingRequest(BaseModel):
    """Toggle a thread's disappearing timer. Just a bool in V1 — on means the 48h
    default, off means messages sent from now on are permanent. A `seconds` field
    would be the natural place to let people pick a duration later; it is absent
    now rather than accepted-and-ignored, so the API never claims a capability the
    service does not yet honour."""

    enabled: bool


class ReportRequest(BaseModel):
    """A report (§23). The reason IS validated here — unlike a message body,
    it is a closed set the client picked from a list we rendered, so an unknown
    value is a client bug rather than a user mistake, and 422 from the schema
    layer says that more precisely than a service check would."""

    reason: str = Field(..., pattern="^(" + "|".join(REPORT_REASONS) + ")$")
    note: str | None = None
    # Context, when reporting from inside a thread. Checked for membership in the
    # service — you cannot staple a stranger's conversation id to a report.
    conversation_public_id: uuid.UUID | None = None
