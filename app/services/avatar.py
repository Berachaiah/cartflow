"""
Profile photo service — validate, upload, swap, remove.

The one place that knows how a `users.profile_image_media_id` comes to exist.
The router does auth and HTTP; `app/integrations/cloudinary_client.py` does the
provider's wire protocol; this module owns the rules.

**Validation, uploading and the `media` row live in `app/services/media.py`**,
shared with message photos. What stays here is only what is specific to a profile
photo. The reasoning behind that validation (no Pillow, Cloudinary as the real
decoder) is recorded there rather than duplicated here.

**Replacement destroys the old asset.** Swapping a photo deletes the previous
Cloudinary file and its `media` row, in that order of importance: the row goes
first (so the user's profile is correct the moment the request returns) and the
remote delete is best-effort afterwards. A failed cleanup leaves one orphaned
file — acceptable — where the reverse order would risk a live `media` row
pointing at an asset that no longer exists.

**Public ids are random, not derived from the user.** `avatars/<uuid4>` rather
than `avatars/<username>`: a guessable id would let anyone fetch a photo the
owner has since removed (Cloudinary URLs are public by design), and it means a
replacement never has to bust a cached URL.
"""

import logging
from dataclasses import dataclass

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import cloudinary_client
from app.models.media import Media
from app.models.user import User
from app.services import media as media_service

logger = logging.getLogger("cartflow.avatar")

# Sub-path under CLOUDINARY_FOLDER. Keeps avatars separable from the message and
# product media that will land in the same account later.
_AVATAR_SUBFOLDER = "avatars"

# The sizes the UI actually renders, so a template asks for a name rather than a
# pixel count. 96 covers every list row and the topbar; 320 is the profile
# header at 2x on a phone.
AVATAR_SIZES = {"sm": 96, "lg": 320}


@dataclass
class AvatarResult:
    """`url` is None after a removal — the same shape either way, so the client
    has one branch instead of two response types."""

    url: str | None


def avatar_url(user: User | None, *, size: str = "sm") -> str | None:
    """The delivery URL for a user's photo, or None if they have none.

    Safe to call for any user and from anywhere, including templates: it reads
    the eager-loaded `profile_image` relationship (see the `lazy="joined"` note
    on the model) and returns None rather than raising when media isn't
    configured, so an install without Cloudinary just shows the default picture.
    """
    if user is None:
        return None
    media = getattr(user, "profile_image", None)
    if media is None or not media.public_id:
        return None
    return cloudinary_client.build_url(
        media.public_id, width=AVATAR_SIZES.get(size, AVATAR_SIZES["sm"])
    )


async def _detach_current(db: AsyncSession, user: User) -> Media | None:
    """Unhook the user's current photo and return its row for cleanup.

    Only the pointer and the row are touched here; the remote file is destroyed
    by the caller after the database work has succeeded.
    """
    media_id = user.profile_image_media_id
    if media_id is None:
        return None

    user.profile_image_media_id = None
    # Also clear the loaded relationship: the ORM would otherwise re-apply the
    # stale object's id on flush, silently undoing the line above.
    user.profile_image = None

    existing = await db.scalar(select(Media).where(Media.id == media_id))
    if existing is not None:
        await db.delete(existing)
    await db.flush()
    return existing


async def set_avatar(db: AsyncSession, user: User, *, file: UploadFile) -> AvatarResult:
    """Validate and store `file` as this user's profile photo.

    Order matters: read and check the bytes, upload, and only then touch the
    database — so a rejected file or a provider outage leaves the account exactly
    as it was, with no half-applied state to reconcile. That ordering is also why
    `media_service.media_row` returns the row un-added rather than adding it: the
    previous photo has to be detached in between.
    """
    media_service.require_media_enabled()
    data = await media_service.read_image_upload(file)

    uploaded = await media_service.upload_to_subfolder(
        data, subfolder=_AVATAR_SUBFOLDER, filename=file.filename or "avatar"
    )

    previous = await _detach_current(db, user)

    media = media_service.media_row(uploaded, owner_id=user.id)
    db.add(media)
    await db.flush()

    user.profile_image_media_id = media.id
    user.profile_image = media
    await db.flush()

    if previous is not None:
        await cloudinary_client.destroy(previous.public_id)

    return AvatarResult(url=avatar_url(user, size="lg"))


async def remove_avatar(db: AsyncSession, user: User) -> AvatarResult:
    """Drop the user's photo, falling them back to the default profile picture.

    Deliberately NOT gated on `media_enabled`: someone whose credentials were
    removed after they uploaded a photo must still be able to take it down. The
    remote delete simply no-ops in that case (`cloudinary_client.destroy`
    returns False rather than raising).
    """
    previous = await _detach_current(db, user)
    if previous is not None:
        await cloudinary_client.destroy(previous.public_id)
    return AvatarResult(url=None)
