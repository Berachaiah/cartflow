"""Pins and chat wallpapers. Every entry point goes through
`messaging_service.require_participant`, so a stranger or a blocked pair gets the
same 404 as everywhere else in messaging."""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ServiceUnavailableError, ValidationAppError
from app.core.timeutils import utc_now
from app.integrations import cloudinary_client
from app.models.conversation import ConversationParticipant, Message
from app.models.media import Media
from app.models.message_extras import (
    MAX_PINS,
    WALLPAPER_PRESETS,
    WALLPAPER_RATIOS,
    ChatWallpaper,
    MessagePin,
)
from app.models.user import User
from app.schemas.message import MessageOut
from app.services import media as media_service
from app.services import messaging as messaging_service

logger = logging.getLogger("cartflow.message_extras")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_uuid(value) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ValidationAppError("That conversation id isn't valid.", fields={"conversation": "Invalid id."})


async def _party_ids(db: AsyncSession, conversation_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(ConversationParticipant.user_id).where(ConversationParticipant.conversation_id == conversation_id)
    )
    return set(rows.scalars().all())


# ---------------------------------------------------------------- pins ----


async def _live_pins(db: AsyncSession, conversation_id: uuid.UUID):
    rows = (
        await db.execute(
            select(MessagePin, Message)
            .join(Message, Message.id == MessagePin.message_id)
            .where(MessagePin.conversation_id == conversation_id, Message.deleted_at.is_(None))
            .order_by(MessagePin.created_at.desc())
        )
    ).all()
    now = utc_now()
    return [(p, m) for p, m in rows if m.expires_at is None or _aware(m.expires_at) > now]


def _pins_payload(rows, viewer_id: uuid.UUID) -> dict:
    return {
        "pins": [
            {
                "message": MessageOut.from_message(m, viewer_id=viewer_id).model_dump(mode="json"),
                "pinned_at": _aware(p.created_at).isoformat() if p.created_at else None,
                "pinned_by_me": p.pinned_by_id == viewer_id,
            }
            for p, m in rows
        ],
        "count": len(rows),
        "max": MAX_PINS,
    }


async def list_pins(db: AsyncSession, *, viewer: User, public_id: uuid.UUID) -> dict:
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    return _pins_payload(await _live_pins(db, conversation.id), viewer.id)


async def _find_message(db: AsyncSession, conversation_id: uuid.UUID, message_public_id: uuid.UUID) -> Message:
    msg = (
        await db.execute(
            select(Message).where(
                Message.public_id == message_public_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if msg is None:
        raise NotFoundError("That message isn't available.")
    return msg


async def pin_message(db: AsyncSession, *, viewer: User, public_id: uuid.UUID, message_public_id: uuid.UUID):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    msg = await _find_message(db, conversation.id, message_public_id)
    if msg.expires_at is not None and _aware(msg.expires_at) <= utc_now():
        raise NotFoundError("That message isn't available.")
    if await db.get(MessagePin, (conversation.id, msg.id)) is None:
        if len(await _live_pins(db, conversation.id)) >= MAX_PINS:
            raise ValidationAppError(
                f"You can pin up to {MAX_PINS} messages in a chat. Unpin one to make room.",
                fields={"message": "Pin limit reached."},
            )
        db.add(MessagePin(conversation_id=conversation.id, message_id=msg.id, pinned_by_id=viewer.id))
        await db.flush()
    return _pins_payload(await _live_pins(db, conversation.id), viewer.id), await _party_ids(db, conversation.id)


async def unpin_message(db: AsyncSession, *, viewer: User, public_id: uuid.UUID, message_public_id: uuid.UUID):
    conversation, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    msg = await _find_message(db, conversation.id, message_public_id)
    pin = await db.get(MessagePin, (conversation.id, msg.id))
    if pin is not None:
        await db.delete(pin)
        await db.flush()
    return _pins_payload(await _live_pins(db, conversation.id), viewer.id), await _party_ids(db, conversation.id)


# ----------------------------------------------------------- wallpapers ----

_DEFAULT = {"kind": "preset", "preset": "default", "image_url": None, "focus_x": 0.5, "focus_y": 0.5,
            "dim": 0, "ratio": None, "scope": "none"}


async def _row_for(db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID | None):
    stmt = select(ChatWallpaper).where(ChatWallpaper.user_id == user_id)
    stmt = (
        stmt.where(ChatWallpaper.conversation_id == conversation_id)
        if conversation_id
        else stmt.where(ChatWallpaper.conversation_id.is_(None))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _payload(db: AsyncSession, row: ChatWallpaper | None) -> dict:
    if row is None:
        return dict(_DEFAULT)
    url = None
    if row.kind == "photo" and row.media_id:
        url = media_service.photo_url(await db.get(Media, row.media_id), width=1600)
    return {
        "kind": "photo" if url else "preset",
        "preset": row.preset or "default",
        "image_url": url,
        "focus_x": row.focus_x,
        "focus_y": row.focus_y,
        "dim": row.dim,
        "ratio": row.ratio,
        "scope": "chat" if row.conversation_id else "all",
    }


async def _scope_id(db: AsyncSession, viewer: User, scope: str, conversation) -> uuid.UUID | None:
    if scope == "all":
        return None
    public_id = _parse_uuid(conversation)
    if public_id is None:
        raise ValidationAppError("Choose a conversation.", fields={"conversation": "Required for this chat."})
    conv, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
    return conv.id


async def resolve_wallpaper(db: AsyncSession, *, viewer: User, conversation) -> dict:
    row = None
    public_id = _parse_uuid(conversation)
    if public_id is not None:
        conv, _ = await messaging_service.require_participant(db, viewer=viewer, public_id=public_id)
        row = await _row_for(db, viewer.id, conv.id)
    if row is None:
        row = await _row_for(db, viewer.id, None)
    return await _payload(db, row)


async def _drop_media(db: AsyncSession, media_id: uuid.UUID | None) -> None:
    if not media_id:
        return
    media = await db.get(Media, media_id)
    if media is None:
        return
    public_id = media.public_id
    await db.delete(media)
    await db.flush()
    try:
        await cloudinary_client.destroy(public_id)
    except Exception:  # best effort: an orphaned remote file is not worth failing the request
        logger.warning("Could not delete wallpaper asset %s", public_id)


async def set_preset(db: AsyncSession, *, viewer: User, scope: str, conversation, preset: str, dim: int = 0) -> dict:
    if preset not in WALLPAPER_PRESETS:
        raise ValidationAppError("That wallpaper doesn't exist.", fields={"preset": "Unknown wallpaper."})
    conversation_id = await _scope_id(db, viewer, scope, conversation)
    row = await _row_for(db, viewer.id, conversation_id)
    old_media = None
    if row is None:
        row = ChatWallpaper(user_id=viewer.id, conversation_id=conversation_id)
        db.add(row)
    else:
        old_media = row.media_id
    row.kind, row.preset, row.media_id = "preset", preset, None
    row.focus_x = row.focus_y = 0.5
    row.ratio, row.dim = None, max(0, min(int(dim), 60))
    await db.flush()
    await _drop_media(db, old_media)
    return await _payload(db, row)


async def set_photo(
    db: AsyncSession, *, viewer: User, scope: str, conversation, file: UploadFile,
    ratio: str | None, dim: int = 0,
) -> dict:
    conversation_id = await _scope_id(db, viewer, scope, conversation)
    if ratio is not None and ratio not in WALLPAPER_RATIOS:
        raise ValidationAppError("That ratio isn't supported.", fields={"ratio": "Unsupported ratio."})
    media_service.require_media_enabled()
    data = await media_service.read_image_upload(file)
    try:
        uploaded = await media_service.upload_to_subfolder(data, subfolder="wallpapers", filename=file.filename)
    except RuntimeError as exc:
        raise ServiceUnavailableError("We couldn't upload that photo. Try again.", fields={"file": "Upload failed."}) from exc
    media = media_service.media_row(uploaded, owner_id=viewer.id)
    db.add(media)
    await db.flush()
    row = await _row_for(db, viewer.id, conversation_id)
    old_media = None
    if row is None:
        row = ChatWallpaper(user_id=viewer.id, conversation_id=conversation_id)
        db.add(row)
    else:
        old_media = row.media_id
    row.kind, row.preset, row.media_id = "photo", None, media.id
    row.focus_x = row.focus_y = 0.5
    row.ratio, row.dim = ratio, max(0, min(int(dim), 60))
    await db.flush()
    await _drop_media(db, old_media)
    return await _payload(db, row)


async def clear_wallpaper(db: AsyncSession, *, viewer: User, scope: str, conversation) -> dict:
    conversation_id = await _scope_id(db, viewer, scope, conversation)
    row = await _row_for(db, viewer.id, conversation_id)
    if row is not None:
        old_media = row.media_id
        await db.delete(row)
        await db.flush()
        await _drop_media(db, old_media)
    return await resolve_wallpaper(db, viewer=viewer, conversation=conversation if scope == "chat" else None)
