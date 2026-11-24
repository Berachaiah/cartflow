"""Queries for the feed and its likes.

Reads that the feed needs are batched rather than per-post: the like state and the
follow state of twenty posts would otherwise be forty extra round trips on the
busiest page in the app.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post, PostLike, PostStatus
from app.models.user import AccountStatus, User, UserFollow

# Statuses that must never surface in a feed, a profile or a liked list. Same set
# the follow graph hides (a suspended account's posts should not keep circulating).
HIDDEN_STATUSES = (AccountStatus.SUSPENDED, AccountStatus.DELETED)


def _visible_posts_stmt():
    """Published, not deleted, authored by a live account."""
    return (
        select(Post, User)
        .join(User, User.id == Post.author_id)
        .where(
            Post.deleted_at.is_(None),
            Post.status == PostStatus.PUBLISHED.value,
            User.deleted_at.is_(None),
            User.account_status.notin_(HIDDEN_STATUSES),
        )
    )


class PostRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def feed(self, *, limit: int = 20) -> list[tuple[Post, User]]:
        """Newest first. The whole feed for V1: there is no follow-only ranking
        (doc 18 is unbuilt), and pretending to rank would be inventing a signal."""
        stmt = _visible_posts_stmt().order_by(Post.created_at.desc()).limit(limit)
        return [(p, u) for p, u in (await self.db.execute(stmt)).all()]

    async def by_author(
        self, author_id: uuid.UUID, *, limit: int = 30
    ) -> list[tuple[Post, User]]:
        """One profile's posts — the same rows Home shows, so a post cannot exist
        in one place and not the other."""
        stmt = (
            _visible_posts_stmt()
            .where(Post.author_id == author_id)
            .order_by(Post.created_at.desc())
            .limit(limit)
        )
        return [(p, u) for p, u in (await self.db.execute(stmt)).all()]

    async def liked_by_user(
        self, user_id: uuid.UUID, *, limit: int = 30
    ) -> list[tuple[Post, User]]:
        """The Liked tab: posts this account liked, newest like first."""
        stmt = (
            _visible_posts_stmt()
            .join(PostLike, PostLike.post_id == Post.id)
            .where(PostLike.user_id == user_id)
            .order_by(PostLike.created_at.desc())
            .limit(limit)
        )
        return [(p, u) for p, u in (await self.db.execute(stmt)).all()]

    async def liked_ids(
        self, *, viewer_id: uuid.UUID | None, post_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Which of these posts the viewer has liked — one query, not one per row."""
        if viewer_id is None or not post_ids:
            return set()
        rows = await self.db.execute(
            select(PostLike.post_id).where(
                PostLike.user_id == viewer_id, PostLike.post_id.in_(post_ids)
            )
        )
        return {row[0] for row in rows.all()}

    async def followed_author_ids(
        self, *, viewer_id: uuid.UUID | None, author_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Which authors the viewer follows — drives the Follow / Following button
        on each card, again in one query."""
        if viewer_id is None or not author_ids:
            return set()
        rows = await self.db.execute(
            select(UserFollow.following_id).where(
                UserFollow.follower_id == viewer_id,
                UserFollow.following_id.in_(author_ids),
            )
        )
        return {row[0] for row in rows.all()}

    async def by_public_id(self, public_id: uuid.UUID) -> Post | None:
        stmt = select(Post).where(Post.public_id == public_id, Post.deleted_at.is_(None))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def add_like(self, *, post: Post, user_id: uuid.UUID) -> bool:
        """Insert the like if it is not there. Returns True when it was added.

        The composite primary key is the uniqueness rule, so the check and the
        insert are one statement's worth of intent: a double-tap finds the row and
        changes nothing rather than raising IntegrityError into a 500.
        """
        existing = await self.db.get(PostLike, {"post_id": post.id, "user_id": user_id})
        if existing is not None:
            return False
        self.db.add(PostLike(post_id=post.id, user_id=user_id))
        post.like_count = max(0, (post.like_count or 0) + 1)
        await self.db.flush()
        return True

    async def remove_like(self, *, post: Post, user_id: uuid.UUID) -> bool:
        """Delete the like if it is there. Returns True when one was removed."""
        result = await self.db.execute(
            delete(PostLike).where(
                PostLike.post_id == post.id, PostLike.user_id == user_id
            )
        )
        if not result.rowcount:
            return False
        post.like_count = max(0, (post.like_count or 0) - 1)
        await self.db.flush()
        return True
