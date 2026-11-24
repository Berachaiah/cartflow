"""Post interactions. One endpoint so far: the like toggle.

Deliberately small. Creating posts from the UI needs a composer that does not
exist yet, and fake-writing one now would be a form nobody can style in time;
what the feed actually cannot do without is a like that persists, because the
card counts likes on every render and Activity can list them.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.services import posts as posts_service

router = APIRouter(prefix="/api/posts", tags=["posts"])


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
