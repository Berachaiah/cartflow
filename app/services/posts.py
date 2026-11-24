"""The feed as the templates already render it.

`to_feed_dict` exists for the same reason `ProductRepository.to_catalog_dict` does:
the card markup in `home.html` was written against a literal, and reshaping the
data to that contract means the design did not have to be rewritten to become
real. Every key here is one the card reads.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutils
from app.models.post import Post
from app.models.user import User
from app.repositories.post import PostRepository


def _thousands(value: int) -> str:
    """`2847` → `2,847`, matching how the hardcoded counts read. Not `naira()`:
    this is a like count, not money, and the currency formatter would print ₦."""
    return f"{int(value):,}"


def to_feed_dict(
    post: Post,
    author: User,
    *,
    liked: bool = False,
    following: bool = False,
    liked_ids: set[uuid.UUID] | None = None,
    followed_ids: set[uuid.UUID] | None = None,
) -> dict:
    """One post as the feed card expects it.

    `time` and `location` are derived, never stored twice: an age is a function of
    `created_at` (a stored "2h" would be wrong by lunchtime) and a location falls
    back to the author's own organization so a post always says where it came from.
    """
    images = [
        {"src": img.get("src"), "alt": img.get("alt") or f"Photo by {author.display_name}"}
        for img in (post.images or [])
        if isinstance(img, dict) and img.get("src")
    ]
    org = author.organization
    location = post.location or (org.official_name if org is not None else "CartFlow")

    return {
        "id": str(post.public_id),
        "author": author.display_name or author.username,
        "handle": author.username,
        "seller": bool(author.is_seller),
        "location": location,
        "time": timeutils.time_ago(post.created_at),
        "following": following,
        "badge": post.badge,
        "media": images,
        "caption": post.body,
        "products": list(post.tagged_product_slugs or []),
        "likes": _thousands(post.like_count or 0),
        "likes_raw": int(post.like_count or 0),
        "comments": _thousands(post.comment_count or 0),
        "liked": liked,
        # No comments table yet, so there is no preview to show. The card skips the
        # block entirely when this is empty rather than inventing a thread.
        "preview": [],
    }


async def _shape(
    db: AsyncSession, rows: list[tuple[Post, User]], *, viewer: User | None
) -> list[dict]:
    """Attach the viewer's like/follow state to a page of rows in two queries."""
    if not rows:
        return []
    repo = PostRepository(db)
    viewer_id = viewer.id if viewer is not None else None
    post_ids = [p.id for p, _ in rows]
    author_ids = list({u.id for _, u in rows})

    liked = await repo.liked_ids(viewer_id=viewer_id, post_ids=post_ids)
    followed = await repo.followed_author_ids(viewer_id=viewer_id, author_ids=author_ids)

    return [
        to_feed_dict(
            post,
            author,
            liked=post.id in liked,
            following=author.id in followed,
        )
        for post, author in rows
    ]


async def feed(
    db: AsyncSession, *, viewer: User | None, limit: int = 20
) -> list[dict]:
    """Home's posts. Newest first, published only."""
    rows = await PostRepository(db).feed(limit=limit)
    return await _shape(db, rows, viewer=viewer)


async def by_author(
    db: AsyncSession, *, author_id: uuid.UUID, viewer: User | None, limit: int = 30
) -> list[dict]:
    """A profile's Posts tab — the same posts Home renders for that account."""
    rows = await PostRepository(db).by_author(author_id, limit=limit)
    return await _shape(db, rows, viewer=viewer)


async def liked_by_user(
    db: AsyncSession, *, user_id: uuid.UUID, viewer: User | None, limit: int = 30
) -> list[dict]:
    """A profile's Liked tab. Private: the route only builds it for the owner."""
    rows = await PostRepository(db).liked_by_user(user_id, limit=limit)
    return await _shape(db, rows, viewer=viewer)


async def toggle_like(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> tuple[bool, int]:
    """Like or unlike one post. Returns (now_liked, like_count).

    A toggle rather than two endpoints because the client has one button: a
    double-tap must land on a state, not a 409, which is the same contract
    `/api/users/{handle}/follow` uses.
    """
    from app.core.exceptions import NotFoundError

    repo = PostRepository(db)
    post = await repo.by_public_id(public_id)
    if post is None:
        raise NotFoundError("That post is no longer available.")

    if await repo.add_like(post=post, user_id=viewer.id):
        liked = True
    else:
        await repo.remove_like(post=post, user_id=viewer.id)
        liked = False

    await db.commit()
    return liked, int(post.like_count or 0)


__all__ = ["by_author", "feed", "liked_by_user", "to_feed_dict", "toggle_like"]
