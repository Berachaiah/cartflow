"""The feed as the templates already render it.

`to_feed_dict` exists for the same reason `ProductRepository.to_catalog_dict` does:
the card markup in `home.html` was written against a literal, and reshaping the
data to that contract means the design did not have to be rewritten to become
real. Every key here is one the card reads.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutils
from app.core.exceptions import ValidationAppError
from app.integrations import cloudinary_client
from app.models.post import Post
from app.models.user import User
from app.repositories.post import PostRepository
from app.services import avatar as avatar_service
from app.services import media as media_service

# The composer's ceiling. Long enough for a caption and a price list, short
# enough that the card cannot be made unreadable by one account — the feed has
# no "see more" truncation, so the limit is what keeps a post a post.
MAX_BODY_CHARS = 2000

# Sub-path under CLOUDINARY_FOLDER, alongside avatars/ and messages/, so a bad
# upload can be traced to the feature that made it.
_POST_SUBFOLDER = "posts"

# Product doc 06 §7: ten images per post. The card renders them as a carousel, so
# the limit is about upload cost and a sane caption-to-photo ratio, not layout.
MAX_POST_IMAGES = 10


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
        # The author's profile photo, or None. The card cannot work this out for
        # itself: `author` above is a display STRING, so there is no User object
        # left in the template to hand to `avatar_src` — which is why the feed
        # drew the default silhouette over every post, even for an account that
        # had uploaded a photo. Resolved here, where the User is in hand, and one
        # joined relationship means no extra query per card.
        "avatar": avatar_service.avatar_url(author, size="sm"),
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


async def create_post(
    db: AsyncSession,
    *,
    author: User,
    body: str,
    files: Sequence[UploadFile] | None = None,
) -> dict:
    """Publish a post by `author`, with up to MAX_POST_IMAGES photos.

    Open to every account, not just businesses: doc 06 §6 gives students image,
    video and text posts, and only the product-tagging half is business-only. The
    author's `is_seller` flag is never consulted here — a student with a phone
    camera and something to say is the point of the feed.

    Order matters for the same reason it does in `avatar_service.set_avatar`: the
    caption is validated, the images are uploaded, and only then is a row
    written. A rejected file or a Cloudinary outage therefore leaves the feed
    exactly as it was, instead of a post that says something the author never
    sent.

    Each photo is stored as a DELIVERY URL (sized, `c_limit`) rather than the
    original `secure_url`, because the card renders every image at 4:5 and
    serving a 12 MP camera file into it would spend the viewer's data on pixels
    that are cropped away. The `media` rows keep the `public_id`s, so a later
    change to that size needs no re-upload.
    """
    text = (body or "").strip()
    # A browser submits an empty file input as one part with no filename; those
    # are not photos, and counting them would fail a text-only post at the limit.
    uploads = [f for f in (files or []) if f is not None and f.filename]

    if not text and not uploads:
        raise ValidationAppError(
            "Write something or add a photo before posting.",
            fields={"body": "A post needs a caption or a photo."},
        )
    if len(text) > MAX_BODY_CHARS:
        raise ValidationAppError(
            f"That post is too long. Keep it under {MAX_BODY_CHARS} characters.",
            fields={"body": f"Maximum is {MAX_BODY_CHARS} characters."},
        )
    if len(uploads) > MAX_POST_IMAGES:
        raise ValidationAppError(
            f"That's too many photos. A post can have up to {MAX_POST_IMAGES}.",
            fields={"files": f"Maximum is {MAX_POST_IMAGES} photos."},
        )

    images: list[dict] | None = None
    if uploads:
        # 503, not 422, when the server has no Cloudinary credentials — that is
        # our configuration problem, not something the author can fix by picking
        # a different file. Text-only posts keep working in that state.
        media_service.require_media_enabled()
        images = []
        for upload in uploads:
            data = await media_service.read_image_upload(upload)
            stored = await media_service.upload_to_subfolder(
                data, subfolder=_POST_SUBFOLDER, filename=upload.filename or "post"
            )
            db.add(media_service.media_row(stored, owner_id=author.id))
            await db.flush()

            images.append(
                {
                    "src": cloudinary_client.build_photo_url(
                        stored.public_id, width=media_service.PHOTO_WIDTH
                    ),
                    # Each slide carries its own alt: the carousel announces
                    # "Photo N of M" from the wrapper, so the alt says whose it is
                    # rather than repeating a position the slide already has.
                    "alt": f"Photo by {author.display_name or author.username}",
                }
            )

    post = Post(author_id=author.id, body=text, images=images)
    db.add(post)
    await db.commit()
    await db.refresh(post)

    return to_feed_dict(post, author, liked=False, following=False)


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


__all__ = [
    "MAX_POST_IMAGES",
    "by_author",
    "create_post",
    "feed",
    "liked_by_user",
    "to_feed_dict",
    "toggle_like",
]
