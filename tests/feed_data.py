"""The sample feed the render tests assert against — one definition.

The feed used to be a literal in `home.html`, and these tests read their expected
photo URLs straight out of that literal. Posts are rows now (`0014_posts`), so the
same expectation has to come from the rows that get seeded. Keeping it in one
module means the trimmed-down test feed and the "every photo reaches the page"
assertion cannot drift: the test asks the data what it should see.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.post import Post, PostStatus
from app.models.user import AccountStatus, AccountType, User

# Three posts, five photos. The middle one is multi-photo on purpose — the
# carousel assertions need a post with more than one slide, and the first post
# being single-photo is the case that used to make those tests read the wrong
# element.
FEED_PHOTOS: dict[str, list[str]] = {
    "retrovibe": ["https://images.test/retrovibe-1.jpg"],
    "sneakerlab": [
        "https://images.test/airflux-side.jpg",
        "https://images.test/airflux-top.jpg",
        "https://images.test/airflux-on-foot.jpg",
    ],
    "campustech": ["https://images.test/desk-setup.jpg"],
}

# (username, display name, badge)
FEED_AUTHORS: list[tuple[str, str, str | None]] = [
    ("retrovibe", "RetroVibe Apparel", "🔥 Trending"),
    ("sneakerlab", "SneakerLab", "✨ New Drop"),
    ("campustech", "CampusTech Store", "⚡ Flash Sale"),
]

ALL_FEED_PHOTOS: list[str] = [src for photos in FEED_PHOTOS.values() for src in photos]


async def seed_feed(session: AsyncSession) -> list[Post]:
    """Create the authors and their posts on `session` and commit.

    Real `User` rows, because the card renders the author's handle, display name
    and Follow button — a post without an author could not be seeded at all, which
    is the point of moving the feed into a table.
    """
    now = datetime.now(timezone.utc)
    posts: list[Post] = []

    for index, (username, display_name, badge) in enumerate(FEED_AUTHORS):
        user = User(
            account_type=AccountType.INDIVIDUAL,
            account_status=AccountStatus.ACTIVE,
            email=f"{username}@sample.cartflow.test",
            username=username,
            username_normalized=username,
            display_name=display_name,
            full_name=display_name,
            is_seller=True,
        )
        session.add(user)
        await session.flush()

        post = Post(
            author_id=user.id,
            body=f"Post {index + 1} from {display_name} #CampusLife",
            images=[
                {"src": src, "alt": f"Photo {n + 1} by {display_name}"}
                for n, src in enumerate(FEED_PHOTOS[username])
            ],
            badge=badge,
            location="Bells University",
            like_count=10 + index,
            comment_count=0,
            status=PostStatus.PUBLISHED.value,
            # Staggered so the feed has a stable, meaningful order.
            created_at=now - timedelta(hours=index + 1),
            updated_at=now - timedelta(hours=index + 1),
        )
        session.add(post)
        posts.append(post)

    await session.commit()
    return posts


def unique_slug(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
