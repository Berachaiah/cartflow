"""
Stories — the rail above the feed, in rows.

The rail shipped as decoration: `home.html` drew shop avatars with a gradient
ring from the product catalogue, and the viewer showed a product photo as if it
were that shop's story. Nothing could be liked, nothing expired, nothing was
anybody's. This module is the table the rail needed, so a story is a post-like
object with an author, a photo, a lifetime, and a record of who saw it.

Three choices worth keeping:

*`expires_at` is a column, not a nightly job.* A story is "live" when
`expires_at` is NULL or in the future. The read layer filters on that, so a
deploy with no cron still never shows a two-day-old story — the same argument
`messages.expires_at` makes. A sweep can delete the rows later; it is not what
makes the rule true.

*Reposts are rows, not a counter.* Reposting copies the photo into a new story
owned by the reposter with `repost_of_id` pointing home. That gives the rail
"Reposted by Ada" naturally, keeps the original author's counts honest, and
means a repost still disappears on its own 24-hour clock instead of reviving
somebody else's story.

*Counts are denormalised, writes are funnelled.* `like_count`, `view_count` and
`repost_count` are mirrors, and `app/services/stories.py` is their only writer —
the same arrangement `posts.like_count` uses.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import (
    Base,
    PublicIdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# 24 hours, the lifetime the product borrows from every app that has a stories
# rail. Stored as a constant on the row's `expires_at` at creation time, so
# changing it later only affects stories created afterwards.
STORY_LIFETIME_HOURS = 24


class Story(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """One slide in someone's story."""

    __tablename__ = "stories"
    __table_args__ = (
        # The rail's own query: live stories, newest first. Composite because
        # "live" alone still sorts the whole table.
        Index("ix_stories_expires_created", "expires_at", "created_at"),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # The line over the photo. Short by design: a story is looked at for a few
    # seconds, and a caption long enough to need scrolling is a post.
    caption: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # A slug, like `posts.tagged_product_slugs`: the story links to
    # /product/{slug} and the facts come from the catalogue at render time.
    tagged_product_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)

    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The story this one reposts, if any. SET NULL so deleting the original
    # leaves the repost standing rather than cascading somebody else's history.
    repost_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # NULL means "never expires" — used by the seeded campus stories, which are
    # demo content a walkthrough must not lose overnight. Everything created
    # through the API sets it.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    author: Mapped["User"] = relationship(lazy="joined")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Story {self.public_id} by {self.author_id}>"


class StoryLike(Base, TimestampMixin):
    """One like per (story, user). The composite PK is the uniqueness rule, so a
    double-tap cannot count twice and unliking is a delete — same as PostLike."""

    __tablename__ = "story_likes"
    __table_args__ = (
        UniqueConstraint("story_id", "user_id", name="uq_story_likes_story_user"),
    )

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class StoryView(Base, TimestampMixin):
    """Who has seen which story.

    Two jobs: the rail's "seen" state (a muted ring) and `story.view_count`.
    A row rather than a localStorage flag because the ring must mean the same
    thing on the phone and the laptop, which is exactly the argument
    `notifications` made against a client-side read flag.
    """

    __tablename__ = "story_views"

    story_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
