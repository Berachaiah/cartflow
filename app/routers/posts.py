"""Post interactions: publish a post, and like one.

The composer posts multipart because a post may carry a photo, and the file must
not be base64'd through a JSON body. Text-only posts send the same form with no
file, so the client has one code path rather than two.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field
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


class CommentRequest(BaseModel):
    """A comment's body only. The author is the session, never the payload — a
    client-supplied author would let anyone comment as anyone."""

    body: str = Field(min_length=1, max_length=600)


@router.get("/{public_id}/comments")
async def list_comments(public_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Every visible comment on one post, oldest first. Public: a comment is not
    private, and a signed-out reader can still read the thread under a post."""
    return {"comments": await posts_service.list_comments(db, public_id=public_id)}


@router.post("/{public_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    public_id: uuid.UUID,
    payload: CommentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Comment as the signed-in account. Returns the comment plus the post's new
    count, so the card can update both without refetching the feed."""
    comment, count = await posts_service.add_comment(
        db, viewer=current_user, public_id=public_id, body=payload.body
    )
    return {"comment": comment, "comment_count": count}


@router.post("/{public_id}/repost")
async def toggle_repost(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    reposted, repost_count = await posts_service.toggle_repost(
        db, viewer=current_user, public_id=public_id
    )
    return {"reposted": reposted, "repost_count": repost_count}


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
