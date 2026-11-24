"""Post interactions: publish a post, and like one.

The composer posts multipart because a post may carry a photo, and the file must
not be base64'd through a JSON body. Text-only posts send the same form with no
file, so the client has one code path rather than two.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.services import posts as posts_service

router = APIRouter(prefix="/api/posts", tags=["posts"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_post(
    body: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Publish a post as the signed-in account, with up to ten photos.

    Any account may post — student or business (doc 06 §6). Nothing here looks at
    `is_seller`; the business-only part of posting is product tagging, which the
    schema already carries and the composer does not offer yet.

    Repeated `files` parts rather than a single `file`: the card is a carousel and
    the doc allows ten, so the endpoint takes the shape the UI can already send.

    Returns the post in the same shape the feed card renders (`to_feed_dict`), so
    the client can show it without a second round trip, and so the composer and
    Home cannot disagree about what a post looks like.

    A photo with no Cloudinary credentials answers 503 rather than 422: the file
    is fine, the server is not configured, and the author should not go hunting
    for a different picture.
    """
    return await posts_service.create_post(
        db, author=current_user, body=body, files=files
    )


@router.post("/{public_id}/like")
async def toggle_like(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Like or unlike. Returns the state the client should paint, not a transition,
    so a double-tap or a retry ends where the user asked to be."""
    liked, like_count = await posts_service.toggle_like(
        db, viewer=current_user, public_id=public_id
    )
    return {"liked": liked, "like_count": like_count}
