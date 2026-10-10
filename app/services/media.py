"""
Image upload plumbing shared by every feature that accepts a photo.

These four functions started life as private helpers in `app/services/avatar.py`
and moved here verbatim when messaging needed the same validation for message
photos (doc 10 §11). Nothing about their behaviour changed in the move —
`avatar.py` imports them under their old names, so the profile-photo path is
byte-for-byte the same code it was before.

What lives here is the *generic* part: is media configured, are these bytes
plausibly an image, how big is too big, and where does the asset land. What does
NOT live here is anything about what the image is FOR — avatars still own
"replacing a photo destroys the old asset", and messaging owns "a photo becomes a
message". A caller composes the two.

The validation strategy is unchanged and worth restating because it looks
under-engineered until you know the reasoning: Pillow is not installed, and
installing an image decoder to parse files uploaded by strangers is not obviously
the safe choice. So three cheap local checks run first — size, magic bytes, and a
chunked read so an oversized body is refused before it is buffered — and then
Cloudinary is the real decoder, off our box and in its own sandbox. The magic-byte
sniff is a fast-fail for the honest mistake (someone picks a PDF), not a security
boundary.
"""

import uuid

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError, ValidationAppError
from app.integrations import cloudinary_client
from app.integrations.cloudinary_client import UploadedImage
from app.models.media import Media, MediaKind, MediaProvider

# 5 MB. Comfortably above a phone camera JPEG after the browser's own resize,
# and small enough that a rejected upload doesn't cost the server much.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Read in 64 KB slices so the cap is enforced *while* reading. Calling
# `await file.read()` first and checking the length afterwards would already
# have the whole body in memory — which is the thing the cap exists to prevent.
_CHUNK = 64 * 1024


def require_media_enabled() -> None:
    if not get_settings().media_enabled:
        raise ServiceUnavailableError(
            "Photo uploads aren't set up on this server yet.",
            fields={"file": "Image hosting is not configured."},
        )


def sniff_image(head: bytes) -> bool:
    """True when `head` starts like an image format Cloudinary can read.

    HEIC/HEIF matters here: it is the iPhone default, so rejecting it would fail
    the most likely upload on the platform we care most about. Cloudinary
    converts it, and f_auto delivers something every browser understands.
    """
    if head.startswith(b"\xff\xd8\xff"):  # JPEG
        return True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":  # WebP
        return True
    if head[:3] == b"GIF":  # GIF
        return True
    # HEIC/HEIF/AVIF: ISO-BMFF, so the brand lives in the `ftyp` box at offset 4.
    if head[4:8] == b"ftyp":
        return True
    return False


async def read_image_upload(
    file: UploadFile, *, max_bytes: int = MAX_IMAGE_BYTES
) -> bytes:
    """Buffer the upload, refusing anything over `max_bytes`.

    Raises ValidationAppError (422) rather than 413: the whole point is that the
    client shows the message next to the file field, and every other field error
    in the app already arrives as 422 with a `fields` map.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            mb = max_bytes // (1024 * 1024)
            raise ValidationAppError(
                f"That image is too large. Please pick one under {mb} MB.",
                fields={"file": f"Maximum size is {mb} MB."},
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise ValidationAppError(
            "No image was uploaded.", fields={"file": "Choose a photo to upload."}
        )
    if not sniff_image(data[:16]):
        raise ValidationAppError(
            "That file doesn't look like a photo. Try a JPG, PNG, WebP or HEIC.",
            fields={"file": "Unsupported file type."},
        )
    return data


async def upload_to_subfolder(
    data: bytes, *, subfolder: str, filename: str | None = None
) -> UploadedImage:
    """Send `data` to `CLOUDINARY_FOLDER/<subfolder>` under a random public id.

    The id is `uuid4().hex`, never derived from the user or the conversation: a
    guessable id would let anyone fetch an image the sender has since deleted
    (Cloudinary URLs are public by design), and randomness means a replacement
    never has to bust a cached URL.
    """
    folder = f"{get_settings().CLOUDINARY_FOLDER.strip('/')}/{subfolder.strip('/')}"
    return await cloudinary_client.upload_image(
        data,
        folder=folder,
        public_id=uuid.uuid4().hex,
        filename=filename or "upload",
    )


def media_row(
    uploaded: UploadedImage, *, owner_id: uuid.UUID, kind: str = MediaKind.IMAGE
) -> Media:
    """Build the `media` row for an uploaded asset.

    Returned un-added: the caller decides when it joins the session, because the
    ordering around it differs per feature (avatars detach the previous photo
    first, messages don't have one).
    """
    return Media(
        owner_user_id=owner_id,
        provider=MediaProvider.CLOUDINARY,
        kind=kind,
        public_id=uploaded.public_id,
        secure_url=uploaded.secure_url,
        width=uploaded.width,
        height=uploaded.height,
        format=uploaded.format,
        bytes=uploaded.bytes,
    )


# Wide enough for a retina phone screen and for the desktop thread pane, which is
# the widest a message photo is ever displayed. Not the original: serving a 12 MP
# camera file into a 400px bubble spends the user's data on pixels they cannot see.
PHOTO_WIDTH = 1080


def photo_url(media: Media | None, *, width: int = PHOTO_WIDTH) -> str | None:
    """Delivery URL for an attached photo, or None if there is nothing to show.

    None rather than "" for a purged or missing row: `messages.media_id` is
    ON DELETE SET NULL precisely so the bubble outlives the file, and the caller
    needs to tell "no photo" from "a photo that is gone" — the second draws a
    placeholder, the first should not have been an IMAGE message at all.

    Mirrors `avatar_service.avatar_url` in shape (safe to call with None, never
    raises when Cloudinary is unconfigured) but goes through
    `build_photo_url`, so a photo is never square-cropped like an avatar.
    """
    if media is None or not media.public_id:
        return None
    return cloudinary_client.build_photo_url(media.public_id, width=width) or None
