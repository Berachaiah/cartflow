"""Stories — the rail's rules, in one place.

The rail and its viewer both read one shape (`rail()`), and every write goes
through this module. That matters more than it sounds: a story's ring, its like
state and its view count are rendered by the server on first paint and by
JavaScript afterwards, so a second implementation anywhere would be a rail that
disagrees with itself.

**Visibility is the feed's visibility.** A story by a suspended or deleted
account must not keep circulating, and it must not appear in the rail of someone
who blocked its author. Both filters live in `_visible()` so no caller can pick
one and forget the other.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Sequence

from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.core import timeutils
from app.integrations import cloudinary_client
from app.models.conversation import UserBlock
from app.models.story import STORY_LIFETIME_HOURS, Story, StoryLike, StoryView
from app.models.user import AccountStatus, User
from app.repositories.post import HIDDEN_STATUSES
from app.services import avatar as avatar_service
from app.services import media as media_service

MAX_CAPTION_CHARS = 300
_STORY_SUBFOLDER = "stories"
# How many slides one render carries. Enough for a campus rail, bounded so a
# table that grows all term cannot turn the home page into a full scan.
RAIL_LIMIT = 80


def _visible():
    """Live stories by live accounts."""
    return (
        select(Story, User)
        .join(User, User.id == Story.author_id)
        .where(
            Story.deleted_at.is_(None),
            User.deleted_at.is_(None),
            User.account_status.notin_(HIDDEN_STATUSES),
            # NULL = never expires (see the model). Written as an explicit OR
            # rather than a coalesce so both dialects plan it the same way.
            (Story.expires_at.is_(None)) | (Story.expires_at > timeutils.utc_now()),
        )
    )


async def _blocked_ids(db: AsyncSession, viewer: User | None) -> set[uuid.UUID]:
    """Accounts either side of a block with the viewer.

    A block is symmetric in effect (see messaging), so both directions are
    filtered: someone you blocked does not appear in your rail, and neither does
    someone who blocked you.
    """
    if viewer is None:
        return set()
    rows = await db.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            (UserBlock.blocker_id == viewer.id) | (UserBlock.blocked_id == viewer.id)
        )
    )
    ids: set[uuid.UUID] = set()
    for blocker, blocked in rows.all():
        ids.add(blocked if blocker == viewer.id else blocker)
    return ids


async def _state(
    db: AsyncSession, rows: Sequence[tuple[Story, User]], *, viewer: User | None
) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    """(liked ids, seen ids, reposted ids) for this page — three queries, not
    three per slide."""
    if viewer is None or not rows:
        return set(), set(), set()
    ids = [story.id for story, _ in rows]
    liked = await db.execute(
        select(StoryLike.story_id).where(
            StoryLike.user_id == viewer.id, StoryLike.story_id.in_(ids)
        )
    )
    seen = await db.execute(
        select(StoryView.story_id).where(
            StoryView.user_id == viewer.id, StoryView.story_id.in_(ids)
        )
    )
    mine = await db.execute(
        select(Story.repost_of_id).where(
            Story.author_id == viewer.id, Story.repost_of_id.in_(ids)
        )
    )
    return (
        set(liked.scalars().all()),
        set(seen.scalars().all()),
        {row for row in mine.scalars().all() if row is not None},
    )


async def rail(db: AsyncSession, *, viewer: User | None, limit: int = RAIL_LIMIT) -> list[dict]:
    """The rail, grouped by author, newest activity first.

    Groups rather than a flat list because the viewer moves through one person's
    slides before the next person's — that is the gesture the progress bars at
    the top of a story describe. Ordering by the author's newest slide keeps a
    brand that just posted at the front, which is the only ranking a rail can
    honestly claim.
    """
    blocked = await _blocked_ids(db, viewer)
    result = await db.execute(
        _visible().order_by(Story.created_at.desc()).limit(limit)
    )
    rows = [(story, author) for story, author in result.all() if author.id not in blocked]

    liked, seen, reposted = await _state(db, rows, viewer=viewer)

    groups: dict[uuid.UUID, dict] = {}
    for story, author in rows:
        group = groups.get(author.id)
        if group is None:
            group = {
                "username": author.username,
                "name": author.display_name or author.username,
                "avatar": avatar_service.avatar_url(author, size="sm"),
                "href": f"/@{author.username}",
                "stories": [],
            }
            groups[author.id] = group
        group["stories"].append(
            {
                "id": str(story.public_id),
                "image": story.image_url,
                "caption": story.caption or "",
                "product": story.tagged_product_slug,
                # Pre-formatted the way the feed's counts are: the card prints
                # the string, so there is one formatter, not two.
                "likes": int(story.like_count or 0),
                "views": int(story.view_count or 0),
                "reposts": int(story.repost_count or 0),
                "liked": story.id in liked,
                "seen": story.id in seen,
                "reposted": story.id in reposted,
                "time": timeutils.time_ago(story.created_at),
                "is_repost": story.repost_of_id is not None,
            }
        )

    for group in groups.values():
        group["seen"] = all(item["seen"] for item in group["stories"])
        group["live"] = not group["seen"]

    return list(groups.values())


async def _one(db: AsyncSession, public_id: uuid.UUID) -> Story:
    story = (
        await db.execute(
            select(Story).where(
                Story.public_id == public_id, Story.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if story is None:
        raise NotFoundError("That story is no longer available.")
    return story


async def toggle_like(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> tuple[bool, int]:
    """Like or unlike one slide. Returns (now_liked, like_count)."""
    story = await _one(db, public_id)
    existing = await db.get(StoryLike, {"story_id": story.id, "user_id": viewer.id})
    if existing is None:
        db.add(StoryLike(story_id=story.id, user_id=viewer.id))
        story.like_count = max(0, (story.like_count or 0) + 1)
        liked = True
    else:
        await db.delete(existing)
        story.like_count = max(0, (story.like_count or 0) - 1)
        liked = False
    await db.commit()
    return liked, int(story.like_count or 0)


async def mark_viewed(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> int:
    """Record that this account opened the slide. Idempotent: a view is a fact,
    not an event, so refreshing a story does not inflate the number."""
    story = await _one(db, public_id)
    if story.author_id == viewer.id:
        return int(story.view_count or 0)
    existing = await db.get(StoryView, {"story_id": story.id, "user_id": viewer.id})
    if existing is None:
        db.add(StoryView(story_id=story.id, user_id=viewer.id))
        story.view_count = max(0, (story.view_count or 0) + 1)
        await db.commit()
    return int(story.view_count or 0)


async def repost(
    db: AsyncSession, *, viewer: User, public_id: uuid.UUID
) -> dict:
    """Put someone's slide in your own story, once.

    A repost is a COPY with a pointer home (see the model), so it disappears on
    its own clock and the original's author still owns the photo. Reposting
    twice is refused rather than silently duplicated — a feed where the same
    story can appear four times because a button was tapped four times is the
    failure mode this check exists to prevent.
    """
    original = await _one(db, public_id)
    if original.author_id == viewer.id:
        raise ValidationAppError("That's already your story.")

    already = (
        await db.execute(
            select(Story.id).where(
                Story.author_id == viewer.id,
                Story.repost_of_id == original.id,
                Story.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        raise ValidationAppError("You've already reposted this story.")

    copy = Story(
        author_id=viewer.id,
        image_url=original.image_url,
        caption=original.caption,
        tagged_product_slug=original.tagged_product_slug,
        repost_of_id=original.id,
        expires_at=timeutils.utc_now() + timedelta(hours=STORY_LIFETIME_HOURS),
    )
    db.add(copy)
    original.repost_count = max(0, (original.repost_count or 0) + 1)
    await db.commit()
    return {"reposts": int(original.repost_count or 0), "reposted": True}


async def create_story(
    db: AsyncSession,
    *,
    author: User,
    caption: str,
    file: UploadFile | None = None,
    product_slug: str | None = None,
) -> dict:
    """Publish a slide.

    A photo is required: a story with no picture is a status update, and the
    viewer has nowhere to put it. Photo hosting must be configured, so an
    install without Cloudinary answers 503 with the same wording the composer
    uses rather than a button whose only outcome is an error.
    """
    text = (caption or "").strip()
    if len(text) > MAX_CAPTION_CHARS:
        raise ValidationAppError(
            f"Keep the caption under {MAX_CAPTION_CHARS} characters.",
            fields={"caption": f"Maximum is {MAX_CAPTION_CHARS} characters."},
        )
    if file is None or not file.filename:
        raise ValidationAppError(
            "A story needs a photo.",
            fields={"file": "Choose a photo for your story."},
        )

    media_service.require_media_enabled()
    data = await media_service.read_image_upload(file)
    stored = await media_service.upload_to_subfolder(
        data, subfolder=_STORY_SUBFOLDER, filename=file.filename or "story"
    )
    db.add(media_service.media_row(stored, owner_id=author.id))

    story = Story(
        author_id=author.id,
        image_url=cloudinary_client.build_photo_url(
            stored.public_id, width=media_service.PHOTO_WIDTH
        ),
        caption=text or None,
        tagged_product_slug=(product_slug or None),
        expires_at=timeutils.utc_now() + timedelta(hours=STORY_LIFETIME_HOURS),
    )
    db.add(story)
    await db.commit()
    return {"id": str(story.public_id), "image": story.image_url}


async def purge_expired(db: AsyncSession) -> int:
    """Hard-delete slides past their lifetime. Not required for correctness —
    `_visible()` already hides them — so this exists for storage, and can run on
    whatever schedule the deployment has."""
    result = await db.execute(
        delete(Story).where(
            Story.expires_at.is_not(None), Story.expires_at <= timeutils.utc_now()
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


__all__ = [
    "MAX_CAPTION_CHARS",
    "RAIL_LIMIT",
    "create_story",
    "mark_viewed",
    "purge_expired",
    "rail",
    "repost",
    "toggle_like",
]
