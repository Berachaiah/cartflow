"""
Follow graph service — the read/write rules for `user_follows`.

The table has existed since the baseline migration (0001_baseline.py:76-86)
and was, until this module, referenced by nothing: no service, no endpoint, no
relationship. Profiles are the first surface that needs it, so the rules live
here rather than in the router.

Three decisions worth stating, because a caller can't infer them:

  - **Follow and unfollow are idempotent.** The profile's Follow button is a
    toggle a user can double-tap on a flaky connection. A second POST returns
    the current state rather than a 409 the UI would have to special-case, and
    a DELETE for a follow that isn't there is a no-op, not a 404.
  - **Counts exclude soft-deleted users.** Rows in `user_follows` survive a
    user's soft delete — there's no cascade and `deleted_at` is on `users` —
    so a naive `COUNT(*)` would keep counting accounts that no longer appear
    anywhere else in the app. Every count joins `users` and filters.
  - **Targets resolve by username here, not in the router**, so every caller
    gets identical treatment for an unknown, soft-deleted, or suspended handle:
    a plain 404 that never confirms the account exists.

**Blocking is enforced here.** Now that `user_blocks` exists (migration 0009),
the check sits inside `resolve_public_user()` — which gates the profile page, the
follower lists, follow, unfollow and every messaging entry point — rather than
being retrofitted into each call site, which is how a block leaks. A blocked pair
gets the same `NotFoundError` as a handle that never existed, in both directions,
so nothing in the response confirms that a block is what happened.

The block predicate itself lives in `ConversationRepository.is_blocked_between`
rather than being re-expressed here. `user_blocks` is declared alongside the
messaging models because messaging is what it exists for, and one definition of
"are these two blocked" is worth an import that reads slightly oddly.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.user import AccountStatus, User, UserFollow
from app.repositories.conversation import ConversationRepository
from app.repositories.user import UserRepository
from app.schemas.user import USERNAME_PATTERN

# Same statuses barred from logging in (session.BLOCKED_LOGIN_STATUSES) are
# barred from having a public profile: an account that can't sign in must not
# keep a reachable page. RESTRICTED still renders — it limits what the account
# can do, not whether it exists.
HIDDEN_PROFILE_STATUSES = {AccountStatus.SUSPENDED, AccountStatus.DELETED}

PROFILE_NOT_FOUND_MESSAGE = "That profile doesn't exist."


@dataclass
class FollowState:
    """The answer to "what does the button say now" after a follow/unfollow."""

    following: bool
    follower_count: int
    # False when the row was already in the wanted state — a double-tap or a
    # retry. The endpoint still returns 200; this is only for observability.
    changed: bool = True


@dataclass
class ProfileStats:
    followers: int
    following: int
    # Viewer → this profile. Always False for a signed-out visitor.
    is_following: bool = False


@dataclass
class FollowRow:
    """One row of a Followers / Following list, pre-annotated with the viewer's
    own relationship to that person so the list's Follow buttons render in the
    right state without a request per row.

    `followed_at` is the EDGE's timestamp, not the person's — when the follow
    happened. The activity inbox needs it to say "2 hours ago", and it comes
    free with the row the list already selects."""

    user: User
    is_following: bool = False
    is_self: bool = False
    followed_at: datetime | None = None


@dataclass
class FollowPage:
    items: list[FollowRow] = field(default_factory=list)
    total: int = 0


# --- count / state building blocks ---------------------------------------
# All three are scalar subqueries so a caller can select several of them in ONE
# round trip (see get_profile_stats) instead of issuing a query per number.


def _followers_count_sq(user_id: uuid.UUID):
    """How many live accounts follow `user_id`."""
    follower = aliased(User)
    return (
        select(func.count())
        .select_from(UserFollow)
        .join(follower, follower.id == UserFollow.follower_id)
        .where(UserFollow.following_id == user_id, follower.deleted_at.is_(None))
        .scalar_subquery()
    )


def _following_count_sq(user_id: uuid.UUID):
    """How many live accounts `user_id` follows."""
    followed = aliased(User)
    return (
        select(func.count())
        .select_from(UserFollow)
        .join(followed, followed.id == UserFollow.following_id)
        .where(UserFollow.follower_id == user_id, followed.deleted_at.is_(None))
        .scalar_subquery()
    )


def _is_following_sq(viewer_id: uuid.UUID, user_id: uuid.UUID):
    """EXISTS rather than a count — the button only needs a boolean."""
    return (
        select(UserFollow.follower_id)
        .where(
            UserFollow.follower_id == viewer_id,
            UserFollow.following_id == user_id,
        )
        .exists()
    )


async def _follower_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(select(_followers_count_sq(user_id)))
    return int(result.scalar_one() or 0)


# --- target resolution ---------------------------------------------------


async def resolve_public_user(
    db: AsyncSession, *, username: str, viewer_id: uuid.UUID | None = None
) -> User:
    """Look up the account behind a `/@handle`, or raise NotFoundError.

    The pattern check runs BEFORE the query for two reasons: it caps the length
    (so a hand-crafted 10 KB path segment never becomes a bound parameter), and
    it makes a malformed handle indistinguishable from a merely absent one.

    Lowercasing is `.lower()`, not `.casefold()`, to match exactly what signup
    stored in `username_normalized` (app/services/auth.py) — casefold maps
    'ß' to 'ss' and would fail to find an account it should.

    `viewer_id` turns on the block check, and every caller that has a signed-in
    user should pass it. It is optional rather than required because a signed-out
    visitor has no blocks to apply, and because the block lookup is an extra
    query nobody should pay for on an anonymous page view.

    A blocked pair raises the SAME NotFoundError with the SAME message as an
    unknown handle. That is the whole point: the blocked party must not be able
    to tell "you blocked me" from "you deleted your account", and the person who
    blocked them must not have their action announced.
    """
    candidate = (username or "").strip()
    if not USERNAME_PATTERN.match(candidate):
        raise NotFoundError(PROFILE_NOT_FOUND_MESSAGE)

    user = await UserRepository(db).get_by_username_normalized(candidate.lower())
    if user is None or user.account_status in HIDDEN_PROFILE_STATUSES:
        raise NotFoundError(PROFILE_NOT_FOUND_MESSAGE)

    # Checked after the account is found, so the cost falls only on real handles,
    # and skipped for self-lookups — you cannot block yourself, and an accidental
    # row saying otherwise must not hide someone's own profile from them.
    if viewer_id is not None and viewer_id != user.id:
        if await ConversationRepository(db).is_blocked_between(viewer_id, user.id):
            raise NotFoundError(PROFILE_NOT_FOUND_MESSAGE)

    return user


# --- writes --------------------------------------------------------------


async def follow_user(db: AsyncSession, *, follower: User, username: str) -> FollowState:
    """Follow `username` as `follower`. Idempotent: following someone you
    already follow returns the current state with changed=False."""
    target = await resolve_public_user(db, username=username, viewer_id=follower.id)

    if target.id == follower.id:
        raise ValidationAppError("You can't follow yourself.")

    changed = await _insert_follow(db, follower_id=follower.id, following_id=target.id)
    return FollowState(
        following=True,
        follower_count=await _follower_count(db, target.id),
        changed=changed,
    )


async def _insert_follow(
    db: AsyncSession, *, follower_id: uuid.UUID, following_id: uuid.UUID
) -> bool:
    """Insert the edge, returning whether a row was actually created.

    The insert runs inside a SAVEPOINT rather than after a "does it exist yet"
    check. Two simultaneous follows would both pass such a check and the second
    INSERT would violate the primary key — and an IntegrityError raised on the
    outer transaction poisons it, so `get_db`'s commit then fails and the user
    gets a 500 for a button they merely double-tapped. Rolling back only the
    savepoint leaves the surrounding transaction usable, and the end state is
    the one the user asked for either way.
    """
    try:
        async with db.begin_nested():
            db.add(UserFollow(follower_id=follower_id, following_id=following_id))
            await db.flush()
    except IntegrityError:
        return False
    return True


async def unfollow_user(db: AsyncSession, *, follower: User, username: str) -> FollowState:
    """Unfollow `username`. Idempotent: unfollowing someone you don't follow is
    a no-op with the same 200, not a 404 — the button's job is to end in the
    'not following' state.

    Idempotency is about the *row*, not the account: an unknown handle is still a
    404, and a blocked pair takes that same branch. In practice it does not come
    up, because `block_user` deletes the follow edges in both directions."""
    target = await resolve_public_user(db, username=username, viewer_id=follower.id)

    result = await db.execute(
        delete(UserFollow).where(
            UserFollow.follower_id == follower.id,
            UserFollow.following_id == target.id,
        )
    )
    await db.flush()

    return FollowState(
        following=False,
        follower_count=await _follower_count(db, target.id),
        changed=bool(result.rowcount),
    )


# --- reads ---------------------------------------------------------------


async def get_profile_stats(
    db: AsyncSession, *, user_id: uuid.UUID, viewer_id: uuid.UUID | None = None
) -> ProfileStats:
    """Both counts plus the viewer's follow state in a SINGLE round trip, so a
    profile render costs 2 queries total (the user lookup and this) no matter
    how many followers are involved."""
    columns = [_followers_count_sq(user_id), _following_count_sq(user_id)]
    if viewer_id is not None and viewer_id != user_id:
        columns.append(_is_following_sq(viewer_id, user_id))

    row = (await db.execute(select(*columns))).one()

    return ProfileStats(
        followers=int(row[0] or 0),
        following=int(row[1] or 0),
        is_following=bool(row[2]) if len(row) > 2 else False,
    )


async def _viewer_following_ids(
    db: AsyncSession, *, viewer_id: uuid.UUID, candidate_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of `candidate_ids` the viewer already follows — one IN query for a
    whole page, rather than a state lookup per row."""
    if not candidate_ids:
        return set()
    stmt = select(UserFollow.following_id).where(
        UserFollow.follower_id == viewer_id,
        UserFollow.following_id.in_(candidate_ids),
    )
    return set((await db.execute(stmt)).scalars().all())


async def _follow_page(
    db: AsyncSession,
    *,
    join_on,
    filter_on,
    user_id: uuid.UUID,
    viewer_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> FollowPage:
    """Shared body of list_followers / list_following — the two differ only in
    which side of the edge is the person and which is the filter.

    `newest edge first` ordering (created_at DESC) matches how every social app
    presents these lists, and the id tiebreak keeps pagination stable when a
    batch of follows shares a timestamp.
    """
    person = aliased(User)

    # The edge's created_at rides along with the person: the activity inbox
    # needs "when", and fetching it here costs nothing over a query that has
    # already joined the edge to order by it.
    base = (
        select(person, UserFollow.created_at)
        .join(UserFollow, join_on(person))
        .where(filter_on == user_id, person.deleted_at.is_(None))
    )

    total = (
        await db.execute(
            select(func.count()).select_from(base.order_by(None).subquery())
        )
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(UserFollow.created_at.desc(), person.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    followed: set[uuid.UUID] = set()
    if viewer_id is not None:
        followed = await _viewer_following_ids(
            db, viewer_id=viewer_id, candidate_ids=[u.id for u, _ in rows]
        )

    return FollowPage(
        items=[
            FollowRow(
                user=u,
                is_following=u.id in followed,
                is_self=viewer_id is not None and u.id == viewer_id,
                followed_at=at,
            )
            for u, at in rows
        ],
        total=int(total or 0),
    )


async def list_followers(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    viewer_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FollowPage:
    """The accounts following `user_id`."""
    return await _follow_page(
        db,
        join_on=lambda person: UserFollow.follower_id == person.id,
        filter_on=UserFollow.following_id,
        user_id=user_id,
        viewer_id=viewer_id,
        limit=limit,
        offset=offset,
    )


async def list_following(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    viewer_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FollowPage:
    """The accounts `user_id` follows."""
    return await _follow_page(
        db,
        join_on=lambda person: UserFollow.following_id == person.id,
        filter_on=UserFollow.follower_id,
        user_id=user_id,
        viewer_id=viewer_id,
        limit=limit,
        offset=offset,
    )
