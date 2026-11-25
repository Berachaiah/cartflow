"""
Messaging endpoints — the inbox, a thread, a send, and the per-thread controls.

    GET    /api/messages                            inbox (?filter=all|unread|requests|archived, ?q=)
                                                    — `archived` is the one tab the inbox query
                                                    cannot be filtered out of `items` for, so it
                                                    is its own branch in the service
    GET    /api/messages/unread                     the nav badge count
    GET    /api/messages/candidates                 the compose picker
    GET    /api/messages/threads/{username}         one thread (?before=, ?limit=)
    POST   /api/messages/threads/{username}         send text / a shared card
    POST   /api/messages/threads/{username}/photo   send a photo (multipart)
    POST   /api/messages/blocks/{username}          block (§22)
    DELETE /api/messages/blocks/{username}          unblock
    POST   /api/messages/reports/{username}         report (§23)
    POST   /api/messages/{public_id}/read           move my read position
    POST   /api/messages/{public_id}/accept         §7 Accept
    POST   /api/messages/{public_id}/decline        §7 Delete
    POST   /api/messages/{public_id}/archive        hide from my inbox
    PATCH  /api/messages/{public_id}/disappearing   turn the 48h timer on/off

**A thread is addressed by handle, a conversation by public id.** Those are two
different things and the split is deliberate. The UI navigates to `/messages/@ada`
— it knows who it wants to talk to, and for someone you have never messaged there
is no conversation to name yet (`get_thread` creates nothing; the first POST does).
Accept, decline, archive, read and the disappearing toggle act on a row that
definitely exists, and take its `public_id`. Routing those by handle instead would
mean re-resolving the pair on every one of them.

**Every rule lives in the service.** §6's one-message state machine, the two block
checks, the rate ceilings, disappearing — none of it is here, and the handlers are
deliberately dull. What *is* here is the live push, because it is the one thing the
service cannot do: `messaging.py` is imported by `schemas/message.py`, so it cannot
import the schema it would need to build a frame (see the docstring of
`services/realtime.py` for the full cycle). The router holds both, so the router
serialises.

**A frame is serialised once per recipient, not once per send.** `MessageOut.is_mine`
is computed against a viewer, and one payload broadcast to both sides would put the
sender's own bubble on the wrong side of the recipient's thread. So `_publish_message`
builds two frames. The sender's own sockets get one too — that is how a second tab
stays in sync, and why the client dedupes by `public_id`.

**Frames are published inside the request transaction**, before `get_db` commits,
which leaves the same narrow window `services/reports.py` accepts for its admin
email: a frame delivered for a send whose transaction then fails. Closing it needs
an after-response hook this app does not have yet. The mitigation is that every
frame is self-contained — the client appends the message from the payload rather
than re-fetching the thread — so it never depends on the write being visible to a
second connection yet.

Success bodies are returned bare; the {data, meta} envelope applies to errors only,
matching the users and organizations routers.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.message import (
    BlockResponse,
    CandidatesResponse,
    ConversationRowOut,
    ConversationStateResponse,
    DisappearingRequest,
    DisappearingResponse,
    InboxResponse,
    MessageOut,
    ReadResponse,
    ReportRequest,
    ReportResponse,
    ReactionRequest,
    SendMessageRequest,
    SendMessageResponse,
    ThreadResponse,
    UnreadResponse,
)
from app.schemas.user import PublicUserOut
from app.services import messaging as messaging_service
from app.services import realtime
from app.services import reports as reports_service

router = APIRouter(prefix="/api/messages", tags=["messaging"])


# --- live push ------------------------------------------------------------


async def _publish_message(
    result: messaging_service.SendResult, *, sender: User, recipient: User
) -> None:
    """Push a delivered message to both sides, serialised once per side.

    `other` is the *counterparty from that recipient's point of view*, so each
    client can file the frame against a thread it addresses by handle without
    working out which of the two names in the payload is the one it means.
    """
    conversation_public_id = str(result.conversation.public_id)
    for viewer, counterpart in ((sender, recipient), (recipient, sender)):
        await realtime.publish(
            {viewer.id},
            {
                "type": "message",
                "conversation": conversation_public_id,
                "other": counterpart.username,
                "status": result.conversation.status,
                "accepted_now": result.accepted_now,
                "message": MessageOut.from_message(
                    result.message, viewer_id=viewer.id
                ).model_dump(mode="json"),
            },
        )


# --- reads ----------------------------------------------------------------


@router.get("", response_model=InboxResponse)
async def get_inbox(
    filter_name: str = Query(default="all", alias="filter"),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """My conversations, newest activity first.

    `filter` is the tab: `all`, `unread`, or `requests`. An unrecognised value
    falls back to All rather than 422 — it arrives from a URL a user can edit, and
    the service treats it that way on purpose.

    `q` is §20's search over the other person's name, handle, or business name. The
    two counts come back on every page because the tabs and the nav badge both
    render them and a client tracking them locally would drift the moment a second
    tab marked something read.

    `has_more` says whether `?offset=` has anything left, answered by over-fetching
    one row rather than counting. It is returned rather than left to the client
    because the client's only alternative is `len(items) == limit`, which is wrong
    on exactly the page that divides evenly — in the direction that offers a "load
    more" leading to nothing.
    """
    view = await messaging_service.get_inbox(
        db,
        viewer=current_user,
        filter_name=filter_name,
        query=q,
        limit=limit,
        offset=offset,
    )
    return InboxResponse(
        items=[
            ConversationRowOut.from_row(row, viewer_id=current_user.id)
            for row in view.rows
        ],
        unread_conversations=view.unread_conversations,
        pending_requests=view.pending_requests,
        has_more=view.has_more,
    )


@router.get("/unread", response_model=UnreadResponse)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Threads with something new in them — just the badge.

    Its own endpoint so the nav can refresh the number without pulling the whole
    inbox down, which is what every page other than /messages needs.
    """
    return UnreadResponse(
        count=await messaging_service.unread_count(db, viewer=current_user)
    )


@router.get("/candidates", response_model=CandidatesResponse)
async def list_candidates(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Who the compose picker offers: people I follow, or who follow me.

    Scoped to the follow graph in the repository, and that is a deliberate refusal
    rather than a shortcut — this is not a user-search endpoint and must not become
    one, because that would be an account-enumeration surface for the sake of a
    convenience feature.
    """
    people = await messaging_service.list_candidates(
        db, viewer=current_user, query=q, limit=limit
    )
    return CandidatesResponse(items=[PublicUserOut.from_user(u) for u in people])


@router.get("/threads/{username}", response_model=ThreadResponse)
async def get_thread(
    username: str,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One thread, by the other person's handle.

    Renders for someone you have never written to: `other` and `can_send` come
    back with an empty message list, which is everything the compose-first screen
    needs. No row is created — the first POST does that.

    `before` pages backwards by `created_at`. Note this does NOT mark anything read
    (that is an explicit POST), so opening a thread in a background tab cannot
    silently clear a badge.
    """
    view = await messaging_service.get_thread(
        db, viewer=current_user, username=username, before=before, limit=limit
    )
    return ThreadResponse.from_view(view, viewer_id=current_user.id)


# --- sends ----------------------------------------------------------------


@router.post("/threads/{username}", response_model=SendMessageResponse)
async def send_message(
    username: str,
    payload: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a message — text, a shared product, or a shared profile.

    The failures worth knowing about from the client side, all decided by §6 in the
    service:

      * **404** — unknown handle, suspended or deleted account, or a block in
        either direction. Identical in all four cases, on purpose (§22): the
        response never reveals that you have been blocked.
      * **409** — you have already sent your one message and they have not answered.
        Temporary, so the client should keep the draft.
      * **403** — they declined your request. Final, so it should not.
      * **429** — too many messages too fast.
      * **422** — empty message, too long, or a share with nothing to share.
    """
    result = await messaging_service.send_message(
        db,
        sender=current_user,
        username=username,
        kind=payload.kind,
        body=payload.body,
        shared_product_slug=payload.shared_product_slug,
        shared_username=payload.shared_username,
        reply_to=payload.reply_to,
    )
    await _publish_message(result, sender=current_user, recipient=result.other)
    return SendMessageResponse.from_result(result, viewer_id=current_user.id)


@router.post("/threads/{username}/photo", response_model=SendMessageResponse)
async def send_photo(
    username: str,
    file: UploadFile = File(...),
    body: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a photo, with an optional caption.

    Multipart rather than JSON, so it matches the avatar upload and the file never
    has to be base64'd through a JSON body. Permission and the rate ceiling are
    checked *before* the upload in the service, so a message you are not allowed to
    send never costs a stored asset. 503 means the server has no Cloudinary
    credentials — the feature is not configured, which is not the same as broken.
    """
    result = await messaging_service.send_photo(
        db, sender=current_user, username=username, file=file, body=body
    )
    await _publish_message(result, sender=current_user, recipient=result.other)
    return SendMessageResponse.from_result(result, viewer_id=current_user.id)


# --- blocking and reporting ----------------------------------------------


@router.post("/blocks/{username}", response_model=BlockResponse)
async def block_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Block an account (§22). Idempotent — blocking someone already blocked is a
    200 with `changed: false`, because the toggle promises a state, not a
    transition.

    Also severs the follow edges in both directions, which unblocking does not
    restore: those were a decision, and undoing a block is not a request to follow
    anyone again.
    """
    changed = await messaging_service.block_user(
        db, blocker=current_user, username=username
    )
    return BlockResponse(blocked=True, changed=changed)


@router.delete("/blocks/{username}", response_model=BlockResponse)
async def unblock_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unblock an account. Also idempotent."""
    changed = await messaging_service.unblock_user(
        db, blocker=current_user, username=username
    )
    return BlockResponse(blocked=False, changed=changed)


@router.post("/reports/{username}", response_model=ReportResponse)
async def report_user(
    username: str,
    payload: ReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """File a report about an account (§23), optionally naming a thread as context.

    Returns a reference the user can quote and nothing else — not whether the row
    was new or folded into an existing open report, since from the reporter's side
    both mean "this has been filed".

    Deliberately still works when the reported account has blocked you: reporting
    resolves the handle without the viewer's block check, so blocking a victim
    cannot be used to switch off reports about yourself.
    """
    report = await reports_service.submit_report(
        db,
        reporter=current_user,
        username=username,
        reason=payload.reason,
        note=payload.note,
        conversation_public_id=payload.conversation_public_id,
    )
    return ReportResponse(reference=report.public_id)


# --- per-conversation state ----------------------------------------------


@router.post("/{public_id}/read", response_model=ReadResponse)
async def mark_read(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move my read position to now, clearing this thread's unread count.

    Monotonic in the service, so a late request from a stale tab cannot move the
    marker backwards. The other side is told over the socket, which is what turns
    their single tick into a double one (§17); `unread` comes back as 0 because by
    definition everything up to now has just been read.
    """
    conversation, last_read_at = await messaging_service.mark_read(
        db, viewer=current_user, public_id=public_id
    )

    # The far side only — a read receipt is about what *they* wrote. My own other
    # tabs learn my read position from their own next fetch.
    audience = await messaging_service.conversation_party_ids(
        db, conversation=conversation
    )
    audience.discard(current_user.id)
    await realtime.publish(
        audience,
        {
            "type": "read",
            "conversation": str(public_id),
            "username": current_user.username,
            "at": last_read_at.isoformat(),
        },
    )
    return ReadResponse(last_read_at=last_read_at, unread=0)


@router.post("/{public_id}/accept", response_model=ConversationStateResponse)
async def accept_request(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """§7 Accept — move a request into the main inbox without answering it yet.

    Only the recipient may accept (403 otherwise); accepting the same thread twice
    is a 200. Note that nobody *has* to press this: replying is accepting, and the
    composer is live on an incoming request already.

    Both sides hear about it, including the initiator — they are now allowed to
    write again, and that is worth knowing immediately.
    """
    conversation = await messaging_service.accept_request(
        db, viewer=current_user, public_id=public_id
    )
    audience = await messaging_service.conversation_party_ids(
        db, conversation=conversation
    )
    await realtime.publish(
        audience,
        {
            "type": "conversation_state",
            "conversation": str(public_id),
            "status": conversation.status,
        },
    )
    return ConversationStateResponse(
        public_id=conversation.public_id, status=conversation.status, archived=False
    )


@router.post("/{public_id}/decline", response_model=ConversationStateResponse)
async def decline_request(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """§7 Delete — refuse a request. The thread leaves my inbox and the sender is
    barred from writing again.

    **The initiator is not told.** No frame goes to the far side, unlike accept:
    telling them their request was declined would make "Delete" into an unwanted
    conversation with the person you were trying to get away from. Only my own
    other tabs are updated, so the row disappears from all of them.
    """
    conversation = await messaging_service.decline_request(
        db, viewer=current_user, public_id=public_id
    )
    await realtime.publish(
        {current_user.id},
        {
            "type": "conversation_state",
            "conversation": str(public_id),
            "status": conversation.status,
            "archived": True,
        },
    )
    return ConversationStateResponse(
        public_id=conversation.public_id, status=conversation.status, archived=True
    )


@router.post("/{public_id}/delete")
async def delete_conversation(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a thread from MY inbox. The other person keeps their copy.

    Distinct from archive, which hides a thread that a new message brings back.
    This drops my participant row for good; if I was the last member the
    conversation and its messages go too. No frame is published to the other
    side: from their point of view nothing happened, which is the point.
    """
    await messaging_service.delete_conversation(
        db, viewer=current_user, public_id=public_id
    )
    await realtime.publish(
        {current_user.id}, {"type": "conversation_deleted", "conversation": str(public_id)}
    )
    return {"deleted": True}


@router.post("/{public_id}/archive", response_model=ConversationStateResponse)
async def archive_conversation(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hide a thread from MY inbox. Per-side, so the other person sees nothing
    change — hence a frame to my own sockets only — and undone automatically the
    next time they write into it."""
    conversation = await messaging_service.archive_conversation(
        db, viewer=current_user, public_id=public_id
    )
    await realtime.publish(
        {current_user.id},
        {
            "type": "conversation_state",
            "conversation": str(public_id),
            "status": conversation.status,
            "archived": True,
        },
    )
    return ConversationStateResponse(
        public_id=conversation.public_id, status=conversation.status, archived=True
    )


@router.post("/{public_id}/unarchive", response_model=ConversationStateResponse)
async def unarchive_conversation(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Put an archived thread back in the inbox — see the Archived tab."""
    conversation = await messaging_service.unarchive_conversation(
        db, viewer=current_user, public_id=public_id
    )
    await realtime.publish(
        {current_user.id},
        {
            "type": "conversation_state",
            "conversation": str(public_id),
            "status": conversation.status,
            "archived": False,
        },
    )
    return ConversationStateResponse(
        public_id=conversation.public_id, status=conversation.status, archived=False
    )


@router.patch("/{public_id}/disappearing", response_model=DisappearingResponse)
async def set_disappearing(
    public_id: uuid.UUID,
    payload: DisappearingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Turn this thread's disappearing timer on (48h) or off.

    Either participant may change it — it is one shared setting per thread, not a
    per-side preference — so both sides get a frame, the way both sides see the
    notice in the apps this mimics.

    The change governs only messages sent **after** it. Each message freezes its own
    expiry at send time, so turning the timer off does not bring back anything that
    has already vanished, and turning it on does not put a clock on messages already
    sent. `changed` is False when the call set the state it was already in.
    """
    conversation, changed = await messaging_service.set_disappearing(
        db, viewer=current_user, public_id=public_id, enabled=payload.enabled
    )
    disappearing = conversation.disappear_after_seconds is not None

    audience = await messaging_service.conversation_party_ids(
        db, conversation=conversation
    )
    await realtime.publish(
        audience,
        {
            "type": "conversation_settings",
            "conversation": str(public_id),
            "username": current_user.username,
            "disappearing": disappearing,
            "disappear_after_seconds": conversation.disappear_after_seconds,
        },
    )
    return DisappearingResponse(
        public_id=conversation.public_id,
        disappearing=disappearing,
        disappear_after_seconds=conversation.disappear_after_seconds,
        changed=changed,
    )


# --- pins and wallpapers (migration 0011) ---------------------------------
import uuid as _uuid
from typing import Literal as _Literal

from fastapi import Query as _Query
from pydantic import BaseModel as _BaseModel

from app.services import message_extras as extras_service


class _PresetBody(_BaseModel):
    scope: _Literal["chat", "all"]
    conversation: _uuid.UUID | None = None
    preset: str
    dim: int = 0


@router.post("/{public_id}/messages/{message_id}/reactions")
async def react_to_message(
    public_id: _uuid.UUID,
    message_id: _uuid.UUID,
    payload: ReactionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle one emoji on one message.

    One endpoint for add and remove: the server is the only party that knows
    whether this user already reacted, so a client's double-tap is a no-op
    rather than a 409 it would have to handle for no product reason.
    """
    result, party = await extras_service.toggle_reaction(
        db,
        viewer=current_user,
        public_id=public_id,
        message_public_id=message_id,
        emoji=payload.emoji,
    )
    await realtime.publish(party, {"type": "reactions", "conversation": str(public_id)})
    return result


@router.delete("/{public_id}/messages/{message_id}")
async def delete_message(
    public_id: _uuid.UUID,
    message_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete for everyone. Sender only; the bubble becomes a tombstone so a
    reply that quotes it still makes sense."""
    result, party = await extras_service.delete_message(
        db, viewer=current_user, public_id=public_id, message_public_id=message_id
    )
    await realtime.publish(party, {"type": "deleted", "conversation": str(public_id)})
    return result


@router.get("/{public_id}/pins")
async def list_pins(
    public_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await extras_service.list_pins(db, viewer=current_user, public_id=public_id)


@router.post("/{public_id}/pins/{message_id}")
async def pin_message(
    public_id: _uuid.UUID,
    message_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await extras_service.pin_message(
        db, viewer=current_user, public_id=public_id, message_public_id=message_id
    )
    await realtime.publish(party, {"type": "pins", "conversation": str(public_id)})
    return payload


@router.delete("/{public_id}/pins/{message_id}")
async def unpin_message(
    public_id: _uuid.UUID,
    message_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await extras_service.unpin_message(
        db, viewer=current_user, public_id=public_id, message_public_id=message_id
    )
    await realtime.publish(party, {"type": "pins", "conversation": str(public_id)})
    return payload


@router.get("/wallpaper")
async def get_wallpaper(
    conversation: _uuid.UUID | None = _Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await extras_service.resolve_wallpaper(db, viewer=current_user, conversation=conversation)


@router.put("/wallpaper")
async def put_wallpaper(
    body: _PresetBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await extras_service.set_preset(
        db, viewer=current_user, scope=body.scope, conversation=body.conversation,
        preset=body.preset, dim=body.dim,
    )


@router.post("/wallpaper/photo")
async def post_wallpaper_photo(
    file: UploadFile = File(...),
    scope: str = Form(...),
    conversation: str | None = Form(default=None),
    ratio: str | None = Form(default=None),
    dim: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if scope not in ("chat", "all"):
        from app.core.exceptions import ValidationAppError as _VAE
        raise _VAE("Choose this chat or all chats.", fields={"scope": "Invalid scope."})
    return await extras_service.set_photo(
        db, viewer=current_user, scope=scope, conversation=conversation, file=file, ratio=ratio, dim=dim
    )


@router.delete("/wallpaper")
async def delete_wallpaper(
    scope: _Literal["chat", "all"] = _Query(...),
    conversation: _uuid.UUID | None = _Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await extras_service.clear_wallpaper(db, viewer=current_user, scope=scope, conversation=conversation)


# --- pinned product and offers (migration 0012) ---------------------------
from app.services import offers as offers_service


class _ProductBody(_BaseModel):
    slug: str
    role: _Literal["seller", "buyer"] = "buyer"


class _SoldBody(_BaseModel):
    sold: bool


class _OfferBody(_BaseModel):
    price: int


class _RespondBody(_BaseModel):
    action: _Literal["accept", "decline", "counter", "withdraw"]
    price: int | None = None


@router.get("/catalog/products")
async def catalog_products(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"items": await offers_service.catalog_items(db)}


@router.get("/{public_id}/deal")
async def get_deal(
    public_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await offers_service.get_deal(db, viewer=current_user, public_id=public_id)


@router.put("/{public_id}/product")
async def put_product(
    public_id: _uuid.UUID,
    body: _ProductBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await offers_service.set_product(
        db, viewer=current_user, public_id=public_id, slug=body.slug, role=body.role
    )
    await realtime.publish(party, {"type": "deal", "conversation": str(public_id)})
    return payload


@router.delete("/{public_id}/product")
async def delete_product(
    public_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await offers_service.clear_product(db, viewer=current_user, public_id=public_id)
    await realtime.publish(party, {"type": "deal", "conversation": str(public_id)})
    return payload


@router.post("/{public_id}/product/sold")
async def post_sold(
    public_id: _uuid.UUID,
    body: _SoldBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await offers_service.set_sold(
        db, viewer=current_user, public_id=public_id, sold=body.sold
    )
    await realtime.publish(party, {"type": "deal", "conversation": str(public_id)})
    return payload


@router.post("/{public_id}/offers")
async def post_offer(
    public_id: _uuid.UUID,
    body: _OfferBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await offers_service.make_offer(
        db, viewer=current_user, public_id=public_id, price=body.price
    )
    await realtime.publish(party, {"type": "deal", "conversation": str(public_id)})
    return payload


@router.post("/{public_id}/offers/{message_id}")
async def post_offer_response(
    public_id: _uuid.UUID,
    message_id: _uuid.UUID,
    body: _RespondBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload, party = await offers_service.respond(
        db, viewer=current_user, public_id=public_id, message_public_id=message_id,
        action=body.action, price=body.price,
    )
    await realtime.publish(party, {"type": "deal", "conversation": str(public_id)})
    return payload
