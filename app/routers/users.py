"""
User endpoints — public profiles, the follow graph, self-edit, and profile photo.

    PATCH  /api/users/me                    edit username / display_name / full_name / bio
    POST   /api/users/me/avatar             upload a profile photo (multipart)
    DELETE /api/users/me/avatar             remove it
    POST   /api/users/{username}/follow     follow (idempotent)
    DELETE /api/users/{username}/follow     unfollow (idempotent)
    GET    /api/users/{username}/followers  paginated, viewer-annotated
    GET    /api/users/{username}/following  paginated, viewer-annotated

Two rules this module exists to enforce:

  - **Nothing here returns `UserOut`** except `/me`, which describes the caller
    to themselves. Everything about another account goes through
    `PublicUserOut` / `FollowUserOut`, which have no `email` field. See the
    comment on `PublicUserOut` for the full exclusion list.
  - **The mutating routes use `get_current_user`, not the optional variant.**
    An action is never guarded by a dependency that can return None (per the
    docstring in app/core/deps.py) — no session means 401, not a silent no-op.

The avatar routes are `/me`-only by design: there is no endpoint to set someone
else's photo, so ownership needs no separate check — the authenticated user *is*
the target.

`/me` is declared before the `/{username}` routes. It can't actually collide
(the others all have a trailing path segment), but the ordering is load-bearing
the moment a bare `GET /api/users/{username}` is added, so it starts correct.

Success bodies are returned bare; the {data, meta} envelope applies to errors
only, matching the organizations and auth routers.
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_optional
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import (
    AvatarResponse,
    FollowListResponse,
    FollowResponse,
    FollowUserOut,
    ProfileUpdateRequest,
    PublicUserOut,
    UserOut,
)
from app.services import account as account_service
from app.services import avatar as avatar_service
from app.services import follow as follow_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit Profile. Applies only the keys the client actually sent, so an
    absent `bio` leaves the existing one alone while an empty one clears it.

    All three names are editable here — `username` (the unique handle),
    `display_name` (public, not unique) and `full_name` (private). The rules live
    in `account_service.update_profile`; the one worth knowing from the client
    side is that a taken handle comes back as a 409 with a per-field message
    under `username`, not a bare error.

    Changing the handle MOVES the profile URL: `/@{old}` stops resolving
    immediately, because nothing records that the old handle used to be this
    account's. The settings form warns before saving.
    """
    changes = payload.model_dump(exclude_unset=True)
    user = await account_service.update_profile(db, current_user, changes=changes)

    return UserOut.model_validate(user)


# --- profile photo -------------------------------------------------------


@router.post("/me/avatar", response_model=AvatarResponse)
async def upload_my_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the caller's profile photo from a multipart upload.

    Everything substantive — the size cap, the format check, the provider call,
    and destroying whatever photo this replaces — lives in the service. The
    interesting failures are worth knowing about from the client side:

      * 422 for a file that is too large, empty, or not an image (with a
        per-field message under `file`, like every other form error in the app).
      * 503 when the server has no Cloudinary credentials — the feature isn't
        configured, which is not the same as broken. The UI reads this and says
        so instead of pretending the upload failed.
    """
    result = await avatar_service.set_avatar(db, current_user, file=file)
    return AvatarResponse(avatar_url=result.url)


@router.delete("/me/avatar", response_model=AvatarResponse)
async def delete_my_avatar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove the caller's photo, reverting them to the default profile picture.

    Idempotent — no photo is a 200 with `avatar_url: null`, matching how the
    follow toggle treats a no-op. And unlike upload, this is not gated on the
    integration being configured: taking a photo down must always work.
    """
    result = await avatar_service.remove_avatar(db, current_user)
    return AvatarResponse(avatar_url=result.url)


# --- follow graph --------------------------------------------------------


@router.post("/{username}/follow", response_model=FollowResponse)
async def follow_user_endpoint(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Follow an account. Idempotent — following someone you already follow
    returns 200 with the current state (`changed: false`) rather than a 409 the
    button would have to special-case. Unknown, suspended, or soft-deleted
    handles are a flat 404; self-follow is 422."""
    state = await follow_service.follow_user(
        db, follower=current_user, username=username
    )
    return FollowResponse(
        following=state.following,
        follower_count=state.follower_count,
        changed=state.changed,
    )


@router.delete("/{username}/follow", response_model=FollowResponse)
async def unfollow_user_endpoint(
    username: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unfollow an account. Also idempotent: no existing edge is a no-op, not a
    404 — the toggle's contract is the end state, not the transition."""
    state = await follow_service.unfollow_user(
        db, follower=current_user, username=username
    )
    return FollowResponse(
        following=state.following,
        follower_count=state.follower_count,
        changed=state.changed,
    )


def _follow_list_response(page: follow_service.FollowPage) -> FollowListResponse:
    """Widen each row's public projection with the viewer's relationship to it.
    Going through `PublicUserOut.from_user` (rather than building the fields
    here) keeps one audited definition of what a public user payload contains."""
    return FollowListResponse(
        items=[
            FollowUserOut(
                **PublicUserOut.from_user(row.user).model_dump(),
                is_following=row.is_following,
                is_self=row.is_self,
            )
            for row in page.items
        ],
        total=page.total,
    )


@router.get("/{username}/followers", response_model=FollowListResponse)
async def list_followers_endpoint(
    username: str,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Who follows this account. Readable while signed out (the profile itself
    is public) — `is_following` is then False on every row rather than absent,
    so the client has one shape to render."""
    target = await follow_service.resolve_public_user(
        db, username=username, viewer_id=current_user.id if current_user else None
    )
    page = await follow_service.list_followers(
        db,
        user_id=target.id,
        viewer_id=current_user.id if current_user else None,
        limit=limit,
        offset=offset,
    )
    return _follow_list_response(page)


@router.get("/{username}/following", response_model=FollowListResponse)
async def list_following_endpoint(
    username: str,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Who this account follows."""
    target = await follow_service.resolve_public_user(
        db, username=username, viewer_id=current_user.id if current_user else None
    )
    page = await follow_service.list_following(
        db,
        user_id=target.id,
        viewer_id=current_user.id if current_user else None,
        limit=limit,
        offset=offset,
    )
    return _follow_list_response(page)
