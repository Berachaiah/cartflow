"""Stories endpoints.

    GET  /api/stories                       the rail, grouped by author
    POST /api/stories                       publish a slide (multipart photo)
    POST /api/stories/{public_id}/like      like / unlike (toggle)
    POST /api/stories/{public_id}/view      record that I opened it
    POST /api/stories/{public_id}/repost    repost it to my own story

Writes require a session (`get_current_user`), reads do not: a signed-out
visitor can look at a campus story, which is what makes the rail worth having on
the landing page. Their likes cannot persist, and the client does not offer the
button until the server says there is a viewer.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_optional
from app.database.session import get_db
from app.models.user import User
from app.services import stories as stories_service

router = APIRouter(prefix="/api/stories", tags=["stories"])


@router.get("")
async def get_rail(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> dict:
    """The rail. Same shape the home page renders server-side, so the viewer
    never has to reconcile two versions of "what is live"."""
    return {"groups": await stories_service.rail(db, viewer=current_user)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_story(
    caption: str = Form(default=""),
    product_slug: str = Form(default=""),
    file: UploadFile = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Publish a photo as a story. Open to every account: a student's story is
    the point of the rail, and nothing here consults `is_seller`."""
    return await stories_service.create_story(
        db,
        author=current_user,
        caption=caption,
        file=file,
        product_slug=product_slug or None,
    )


@router.post("/{public_id}/like")
async def like_story(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    liked, like_count = await stories_service.toggle_like(
        db, viewer=current_user, public_id=public_id
    )
    return {"liked": liked, "like_count": like_count}


@router.post("/{public_id}/view")
async def view_story(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"view_count": await stories_service.mark_viewed(
        db, viewer=current_user, public_id=public_id
    )}


@router.post("/{public_id}/repost")
async def repost_story(
    public_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await stories_service.repost(db, viewer=current_user, public_id=public_id)
