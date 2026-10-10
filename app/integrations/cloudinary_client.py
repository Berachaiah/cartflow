"""
Cloudinary image hosting — signed upload, delete, and delivery-URL building.

Hand-rolled on httpx rather than the `cloudinary` SDK, for the same reasons
app/services/google_oauth.py skips an OAuth library: the surface we need is one
HTTP call plus a SHA-1 signature, httpx is already a requirement, and adding a
dependency to the venv is the operator's call, not this module's.

Three things worth understanding before changing this file:

*Signed, server-side uploads.* The browser never talks to Cloudinary. It POSTs
the file to us, we sign the request with CLOUDINARY_API_SECRET and forward it.
So the secret never reaches a client, and no "unsigned upload preset" has to be
enabled on the account — an unsigned preset is a public write endpoint, which is
not something to turn on for avatars.

*Metadata is stripped at rest, not just on delivery.* Uploads carry an INCOMING
transformation (`transformation=` on the upload call), so what Cloudinary stores
is already re-encoded. That drops EXIF — including the GPS coordinates a phone
camera writes — from the stored original. Stripping only on the delivered
derivative would leave the raw file, GPS and all, fetchable at its own URL.

*One stored id, every size derived at delivery.* We persist `public_id` and
build sized URLs on demand (`build_url`), instead of uploading a thumbnail set.
That is the whole point of using Cloudinary, and it means a design change that
wants a bigger avatar needs no re-upload.

Folders: `CLOUDINARY_FOLDER` is a path prefix, nothing more. Cloudinary creates
it on first upload if it doesn't already exist, so a mismatch between the
setting and a folder made in the console is harmless.
"""

import hashlib
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.exceptions import ValidationAppError

logger = logging.getLogger("cartflow.cloudinary")

_API_BASE = "https://api.cloudinary.com/v1_1"
_DELIVERY_BASE = "https://res.cloudinary.com"

# Applied to the bytes we send BEFORE Cloudinary stores them (see module
# docstring). c_limit only shrinks — a 400px avatar is not upscaled to 1024 —
# and q_auto re-encodes, which is what actually discards the metadata.
_INCOMING_TRANSFORMATION = "c_limit,w_1024,h_1024,q_auto"

# Delivery transformation for avatars: square crop, biased toward whatever the
# subject is (g_auto), automatic quality, and f_auto so a browser that accepts
# WebP/AVIF gets it. Faces end up centred without us running face detection.
_AVATAR_TRANSFORMATION = "c_fill,g_auto,q_auto,f_auto"

# Delivery transformation for a photo shown as itself — a message attachment.
# c_limit, NOT c_fill: an avatar is a fixed circle so cropping to it is right,
# but cropping a photo somebody sent would silently remove part of what they
# meant to send. No g_auto for the same reason — there is nothing to centre on
# when the whole frame is the content.
_PHOTO_TRANSFORMATION = "c_limit,q_auto,f_auto"

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class UploadedImage:
    """What we keep from Cloudinary's upload response. `public_id` is
    authoritative and comes back from the API — we never reconstruct it from the
    folder + name we asked for, because Cloudinary is free to normalize it."""

    public_id: str
    secure_url: str
    width: int | None = None
    height: int | None = None
    format: str | None = None
    bytes: int | None = None


def _signature(params: dict[str, str], api_secret: str) -> str:
    """Cloudinary's signature: SHA-1 over the params sorted by key and joined
    `k=v&k=v`, with the API secret appended. `file`, `api_key` and
    `resource_type` are excluded by the spec — callers must not pass them in."""
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1(f"{payload}{api_secret}".encode()).hexdigest()


def _require_config() -> tuple[str, str, str]:
    settings = get_settings()
    if not settings.media_enabled:
        # Callers should check `settings.media_enabled` and answer 503 before
        # getting here; this is the backstop that keeps an unconfigured install
        # from emitting a request signed with `None`.
        raise RuntimeError("Cloudinary is not configured (CLOUDINARY_* unset).")
    return (
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    )


async def upload_image(
    data: bytes,
    *,
    folder: str,
    public_id: str,
    filename: str = "upload",
) -> UploadedImage:
    """Upload `data` as an image and return what to persist.

    `folder` + `public_id` combine into the final id (`folder/public_id`).
    Raises ValidationAppError when Cloudinary rejects the bytes — which is also
    the app's real image validation: Cloudinary decodes the file off our box, so
    a malicious payload is never parsed in-process. Anything else (network,
    5xx, auth) raises RuntimeError, because it is our problem, not the user's.
    """
    cloud_name, api_key, api_secret = _require_config()

    signed = {
        "folder": folder,
        "public_id": public_id,
        "timestamp": str(int(time.time())),
        "transformation": _INCOMING_TRANSFORMATION,
    }
    form = {
        **signed,
        "api_key": api_key,
        "signature": _signature(signed, api_secret),
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_API_BASE}/{cloud_name}/image/upload",
                data=form,
                files={"file": (filename, data)},
            )
    except httpx.HTTPError as exc:
        logger.warning("Cloudinary upload failed to complete: %s", exc)
        raise RuntimeError("Could not reach the image host.") from exc

    if resp.status_code in (400, 420, 422):
        # Cloudinary's own message is descriptive ("Invalid image file") but it
        # is a third-party string; log it and show the user something stable.
        logger.info("Cloudinary rejected an upload: %s", resp.text[:400])
        raise ValidationAppError(
            "That file doesn't look like an image we can use. Try a JPG, PNG or WebP.",
            fields={"file": "Unsupported or corrupted image."},
        )
    if resp.status_code >= 400:
        logger.error(
            "Cloudinary upload error %s: %s", resp.status_code, resp.text[:400]
        )
        raise RuntimeError("The image host returned an error.")

    body = resp.json()
    returned_id = body.get("public_id")
    secure_url = body.get("secure_url")
    if not returned_id or not secure_url:
        logger.error("Cloudinary upload response missing fields: %s", body)
        raise RuntimeError("The image host returned an unexpected response.")

    return UploadedImage(
        public_id=returned_id,
        secure_url=secure_url,
        width=body.get("width"),
        height=body.get("height"),
        format=body.get("format"),
        bytes=body.get("bytes"),
    )


async def destroy(public_id: str) -> bool:
    """Delete an asset. Best-effort by design: the caller has already replaced
    the user's avatar by the time this runs, so a failure here means one orphaned
    file — never a failed request the user has to retry. Returns success."""
    try:
        cloud_name, api_key, api_secret = _require_config()
    except RuntimeError:
        return False

    signed = {"public_id": public_id, "timestamp": str(int(time.time()))}
    form = {**signed, "api_key": api_key, "signature": _signature(signed, api_secret)}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_API_BASE}/{cloud_name}/image/destroy", data=form
            )
    except httpx.HTTPError as exc:
        logger.warning("Cloudinary destroy failed for %s: %s", public_id, exc)
        return False

    if resp.status_code >= 400:
        logger.warning(
            "Cloudinary destroy %s returned %s: %s",
            public_id,
            resp.status_code,
            resp.text[:200],
        )
        return False
    return resp.json().get("result") == "ok"


def build_url(public_id: str, *, width: int, height: int | None = None) -> str:
    """Delivery URL for a square avatar derivative at `width` px.

    The version segment is omitted on purpose: every upload gets a fresh random
    public_id, so a URL never has to be busted — and omitting it keeps the id
    the single thing we store. No extension either; f_auto negotiates the format
    from the request's Accept header.
    """
    cloud_name = get_settings().CLOUDINARY_CLOUD_NAME
    if not cloud_name or not public_id:
        return ""
    box = f"w_{width},h_{height or width}"
    return (
        f"{_DELIVERY_BASE}/{cloud_name}/image/upload/"
        f"{_AVATAR_TRANSFORMATION},{box}/{public_id}"
    )


def build_photo_url(public_id: str, *, width: int) -> str:
    """Delivery URL for a photo at its own aspect ratio, capped at `width` px.

    Same URL shape as `build_url` — no version, no extension, for the same two
    reasons — but a bounding width instead of a box: only the long edge is
    constrained, so a portrait photo stays portrait. `c_limit` also never
    upscales, so a small image is served at its native size rather than blown up
    and blurred.
    """
    cloud_name = get_settings().CLOUDINARY_CLOUD_NAME
    if not cloud_name or not public_id:
        return ""
    return (
        f"{_DELIVERY_BASE}/{cloud_name}/image/upload/"
        f"{_PHOTO_TRANSFORMATION},w_{width}/{public_id}"
    )
