"""
Posts — the feed in rows (docs/product/06-home-feed-and-social-features.md).

The feed used to be a Jinja literal in `home.html`: five hand-written posts with
hardcoded images and like counts. That was fine as a design target and wrong as a
feature — a post could not belong to anybody, so it could not appear on a profile,
could not be liked by a real account, and could not show a notification. The
marketplace had already made this move (products went from a curated list to a
table, see `app/models/product.py`); this is the same move for the feed, and it is
what makes Home, `/@handle` and Activity agree about the same post.

Three choices worth keeping:

*`images` is JSON, not a media table.* Nothing uploads post photos yet and the
sample posts carry Unsplash URLs, exactly like `products.image_url`. The shape is
a list of `{"src": ..., "alt": ...}` because the card renders a carousel and each
slide needs its own alt text — a single URL column would force the template to
invent an alt for photos 2..n.

*`like_count` is denormalized.* The card prints a number on every post in the
feed; counting `post_likes` per post would be a subquery per row. `PostLike` is the
truth and this is the mirror, updated in the one place that inserts or deletes a
like (`app/services/posts.py`), the same arrangement `conversations.last_message_*`
uses.

*`tagged_product_slugs` holds slugs, not ids.* A tagged product is a link the feed
renders from the catalogue's own projection, and a slug is what `/product/{slug}`
takes. Storing ids would mean a second lookup to build a URL, and a post that
tagged a since-archived product would still have to render (or drop) the tag —
which the template already does by looking the slug up and skipping when it does
not resolve.
"""

import enum
import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import (
    Base,
    PublicIdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class PostStatus(str, enum.Enum):
    """Only `published` is rendered. `hidden` exists so moderation can take a
    post out of the feed without deleting the row a report points at."""

    PUBLISHED = "published"
    HIDDEN = "hidden"


class Post(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """One feed post. Authored by a user, not an organization: a student seller
    posts as themselves and their shop is a link away, which is what the profile
    already does with `is_seller`."""

    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("like_count >= 0", name="ck_posts_like_count_non_negative"),
        # The feed's own ordering: newest first, filtered to published rows.
        Index("ix_posts_status_created_at", "status", "created_at"),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    body: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"src": url, "alt": text}] — see the module docstring.
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tagged_product_slugs: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # The small pill over the photo ("Trending", "Flash Sale", "25-35 min"). Free
    # text because these are commerce labels a seller chooses, not a state machine.
    badge: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Shown in the meta line next to the age. Defaults to the author's school when
    # empty, so a post always says where it came from.
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)

    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Mirrors of the two tables below, for the same reason `like_count` is: the
    # card prints a number on every post in the feed, and counting rows per post
    # would be two subqueries per card. `app/services/posts.py` is the only
    # writer of either.
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PostStatus.PUBLISHED.value, index=True
    )

    author: Mapped["User"] = relationship(lazy="joined")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Post {self.public_id} by {self.author_id}>"


class PostComment(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """One comment on one post.

    Shaped like a chat message rather than a threaded forum: V1 has no replies
    to replies, so a `parent_comment_id` would be a column nothing writes. The
    feed shows the newest two as a preview and the card expands to the rest —
    which is why the index is (post_id, created_at): both reads are "the newest
    comments on this post".

    `author` is joined eagerly because every render prints the name and photo;
    a lazy load outside the request's greenlet raises MissingGreenlet under
    async SQLAlchemy, the same reason `Post.author` is joined.
    """

    __tablename__ = "post_comments"
    __table_args__ = (Index("ix_post_comments_post_created", "post_id", "created_at"),)

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    author: Mapped["User"] = relationship(lazy="joined")  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PostComment on {self.post_id}>"


class PostRepost(Base, TimestampMixin):
    """One repost per (post, user), like PostLike: the composite PK is the rule,
    so a double-tap cannot inflate the count and un-reposting is a delete.

    Reposts are recorded rather than copied (unlike stories): a feed post is
    addressed by its own id, so "Ada reposted this" is a fact about the same
    post, and duplicating the row would split its likes and comments in two.
    """

    __tablename__ = "post_reposts"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_reposts_post_user"),)

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class PostLike(Base, TimestampMixin):
    """One like per (post, user). The composite primary key IS the uniqueness
    rule, so a double-tap cannot count twice and unliking is a delete."""

    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_likes_post_user"),)

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
