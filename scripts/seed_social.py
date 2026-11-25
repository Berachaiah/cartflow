"""
Dev-only social seeder — live stories and real comments on the demo feed.

WHY THIS EXISTS.

`seed_posts.py` gives the feed seven brand posts with their own product photos,
and the story rail and the comment previews read from tables that were empty, so
both surfaces rendered their empty state: "No stories yet today", and cards with
a comment count of zero. An empty demo cannot show what the feature does.

The content follows the same rule as the posts it sits on: nothing is invented
about a real brand. A story uses that brand's own product photo and tags the
product slug the catalogue already has, so the ring, the slide and the product
page cannot disagree. A comment is a short reaction from one of the demo
accounts — the same accounts the likes in `seed_posts.py` come from — rather
than an invented customer testimonial.

Numbers. View and like counts are demo figures, the same way `like_count` on the
seeded posts is: `STORY_VIEWS` / `STORY_LIKES` are the baseline, and the real
`story_likes` rows this script inserts are ADDED on top, so tapping like on a
seeded story still moves the number by one. `post.comment_count` is never
written from a table above — it is recomputed from the rows inserted, which is
the same invariant `services/posts.add_comment` maintains.

Reposts follow the same shape: `post_reposts` rows are real (one per post and
account, the composite PK being the rule `services/posts.toggle_repost` relies
on), and `repost_count` is recounted from them after the insert. It is never an
invented number, so the card's "N reposts" line and the button's next tap agree.

Stories are seeded with `expires_at = NULL` (never expires). A walkthrough has
to survive overnight; the API still sets a 24-hour clock on everything people
create.

SAFETY. SQLite only, refuses anything else. Idempotent: a story is identified by
(author, caption) and a comment by (post, author, body), so re-running adds
nothing twice. `--reset` deletes every story, story like/view and comment first,
then rebuilds — the way to replace a caption.

Run:
    ./.venv/Scripts/python.exe scripts/seed_social.py --reset
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./dev_preview.db"

import app.models  # noqa: F401,E402  — registers every mapper before use
from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.database.session import engine  # noqa: E402
from app.models.post import Post, PostComment, PostRepost  # noqa: E402
from app.models.story import Story, StoryLike, StoryView  # noqa: E402
from app.models.user import User  # noqa: E402

B = "/static/images/brands"
U = "https://images.unsplash.com/photo-1556821840-3a63f95609a7?q=80&w=900&auto=format&fit=crop"

# (author handle, image, caption, tagged slug, baseline likes, baseline views, hours ago)
STORIES: list[tuple] = [
    (
        "bastilluxeapparel",
        f"{B}/bastilluxe-bx25-jersey.jpg",
        "Drop 02 is live. BX25 in bubblegum pink — tap the tag to shop it.",
        "bastilluxe-bx25-jersey",
        412,
        2140,
        2,
    ),
    (
        "bastilluxeapparel",
        f"{B}/bastilluxe-seraph-tee.jpg",
        "Seraph, restocked through XXL. Same heavyweight cut.",
        "bastilluxe-seraph-tee",
        268,
        1580,
        5,
    ),
    (
        "mbl.label",
        f"{B}/mbl-midnight-skully.webp",
        "Midnight Skully, back on the shelf this morning.",
        "mbl-midnight-skully",
        190,
        1204,
        3,
    ),
    (
        "mbl.label",
        f"{B}/mbl-world-cup-tee.webp",
        "Heroes Are Made — front map, the line across the back.",
        "mbl-world-cup-tee",
        143,
        905,
        6,
    ),
    (
        "elexandco",
        f"{B}/elex-cipher-bracelet.jpg",
        "The Cipher, hand-finished in the studio this week.",
        "elex-cipher-bracelet",
        96,
        640,
        7,
    ),
    (
        "thebest",
        U,
        "Hoodie weather on campus. Pickup at Faculty Road or your hostel.",
        "campus-essential-hoodie",
        320,
        1750,
        4,
    ),
    (
        "studentuser",
        "/static/images/products/jollof-rice-combo.jpg",
        "Lunch is out — jollof, grilled chicken, plantain on the side.",
        "jollof-rice-combo",
        88,
        512,
        1,
    ),
]

# Which real accounts have liked / seen a story. Kept small and honest: these
# are the same demo accounts that like posts, not a fabricated crowd.
STORY_LIKERS = {
    "bastilluxeapparel": ["studentuser", "thebest"],
    "mbl.label": ["studentuser", "thebest"],
    "elexandco": ["thebest"],
    "thebest": ["studentuser"],
    "studentuser": ["thebest"],
}
STORY_VIEWERS = ["studentuser", "thebest", "cartflow"]

# (post body prefix, [(author handle, comment body, minutes after the post left)])
COMMENTS: list[tuple[str, list[tuple[str, str, int]]]] = [
    (
        "Drop 02 is live.",
        [
            ("studentuser", "That pink is loud in the best way. Is M still there?", 40),
            ("thebest", "Saw someone in this at the faculty building today.", 95),
            ("mbl.label", "Piping detail is clean. Respect.", 150),
        ],
    ),
    (
        "Seraph, restocked.",
        [
            ("thebest", "Bought the first run — still the tee I reach for.", 120),
            ("studentuser", "Does the XXL fit boxy like the photos?", 300),
        ],
    ),
    (
        "Midnight Skully is back.",
        [
            ("studentuser", "Been waiting on this restock. Picking one up in Yaba.", 55),
            ("thebest", "Embroidered script looks better in person.", 210),
        ],
    ),
    (
        "Heroes Are Made.",
        [
            ("bastilluxeapparel", "The back print is the whole tee.", 130),
            ("studentuser", "Loving the map graphic.", 380),
        ],
    ),
    (
        "The Cipher.",
        [
            ("thebest", "Does the clasp adjust small enough for a wrist?", 75),
            ("studentuser", "The spacers catch the light properly.", 190),
        ],
    ),
    (
        "Hoodie weather is back on campus.",
        [
            ("studentuser", "Grey, size L, pickup at Faculty Road please.", 65),
            ("mbl.label", "Heavyweight fleece always wins.", 240),
        ],
    ),
    (
        "Lunch sorted.",
        [
            ("thebest", "Ordered at 12 and it was still hot. Plantain was the right call.", 30),
            ("studentuser", "Batching from 11 is the detail people miss.", 110),
        ],
    ),
]

# (post body prefix, [handles who reposted it]) — demo accounts only, the same
# ones that like and comment, so a reposted post is a real row for a real user.
REPOSTS: list[tuple[str, list[str]]] = [
    ("Drop 02 is live.", ["studentuser", "thebest"]),
    ("Seraph, restocked.", ["studentuser"]),
    ("Midnight Skully is back.", ["studentuser", "thebest"]),
    ("Heroes Are Made.", ["studentuser"]),
    ("The Cipher.", ["thebest"]),
    ("Hoodie weather is back on campus.", ["studentuser", "mbl.label"]),
    ("Lunch sorted.", ["thebest"]),
    # The three posts below are not from seed_posts.py (they were written in the
    # app), but they sit in the same feed, and a zero beside the others reads as
    # a broken count rather than a quiet post.
    ("Restock day", ["studentuser", "thebest"]),
    ("Anyone selling a desk lamp", ["mbl.label"]),
    ("Two-piece fit", ["studentuser"]),
]


async def main(reset: bool) -> None:
    if not os.environ["DATABASE_URL"].startswith("sqlite"):
        sys.exit("Refusing to seed a non-SQLite database.")

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    async with Session() as db:
        people = {
            u.username.lower(): u for u in (await db.execute(select(User))).scalars().all()
        }
        needed = {handle for handle, *_ in STORIES} | {
            handle for _, rows in COMMENTS for handle, _, _ in rows
        }
        missing = {handle for handle in needed if handle.lower() not in people}
        if missing:
            sys.exit(
                f"Missing accounts: {sorted(missing)}. "
                "Run scripts/seed_products.py and scripts/seed_posts.py first."
            )

        posts = (await db.execute(select(Post))).scalars().all()
        if not posts:
            sys.exit(
                "No posts to comment on. Run scripts/seed_posts.py first — comments "
                "hang off the posts it creates."
            )

        if reset:
            # Children first: the likes and views have no ON DELETE CASCADE in
            # SQLite's default (foreign keys are off unless enabled), so deleting
            # stories first would leave orphans behind.
            await db.execute(delete(StoryLike))
            await db.execute(delete(StoryView))
            await db.execute(delete(Story))
            await db.execute(delete(PostComment))
            await db.execute(delete(PostRepost))
            await db.commit()
            print("Reset: removed every story, story like/view, comment and repost.")

        # ---- stories ------------------------------------------------------
        added = 0
        by_author: dict[str, list[Story]] = {}
        for handle, image, caption, slug, likes, views, hours_ago in STORIES:
            author = people[handle.lower()]
            exists = (
                await db.execute(
                    select(Story).where(
                        Story.author_id == author.id, Story.caption == caption
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                created = now - timedelta(hours=hours_ago)
                story = Story(
                    author_id=author.id,
                    image_url=image,
                    caption=caption,
                    tagged_product_slug=slug,
                    like_count=likes,
                    view_count=views,
                    expires_at=None,
                    created_at=created,
                    updated_at=created,
                )
                db.add(story)
                by_author.setdefault(handle.lower(), []).append(story)
                added += 1
        await db.flush()

        # ---- real likes and views on those stories ------------------------
        made_likes = made_views = 0
        stories = (
            await db.execute(
                select(Story).where(Story.caption.in_([s[2] for s in STORIES]))
            )
        ).scalars().all()
        for story in stories:
            author = next(
                (h for h, *_ in STORIES if people[h.lower()].id == story.author_id), None
            )
            for liker_handle in STORY_LIKERS.get(author or "", []):
                liker = people.get(liker_handle.lower())
                if liker is None:
                    continue
                existing = await db.get(StoryLike, {"story_id": story.id, "user_id": liker.id})
                if existing is None:
                    db.add(StoryLike(story_id=story.id, user_id=liker.id))
                    story.like_count = (story.like_count or 0) + 1
                    made_likes += 1
            for viewer_handle in STORY_VIEWERS:
                viewer = people.get(viewer_handle.lower())
                if viewer is None:
                    continue
                existing = await db.get(StoryView, {"story_id": story.id, "user_id": viewer.id})
                if existing is None:
                    db.add(StoryView(story_id=story.id, user_id=viewer.id))
                    story.view_count = (story.view_count or 0) + 1
                    made_views += 1
        await db.commit()
        print(f"Added {added} stories, {made_likes} likes, {made_views} views.")

        # ---- comments -----------------------------------------------------
        made_comments = 0
        for prefix, rows in COMMENTS:
            post = next((p for p in posts if p.body.startswith(prefix)), None)
            if post is None:
                print(f"  post not found, skipping comments: {prefix!r}")
                continue
            for handle, body, minutes_after in rows:
                author = people[handle.lower()]
                existing = (
                    await db.execute(
                        select(PostComment).where(
                            PostComment.post_id == post.id,
                            PostComment.author_id == author.id,
                            PostComment.body == body,
                            PostComment.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                created = post.created_at + timedelta(minutes=minutes_after)
                db.add(
                    PostComment(
                        post_id=post.id,
                        author_id=author.id,
                        body=body,
                        created_at=created,
                        updated_at=created,
                    )
                )
                made_comments += 1
            await db.flush()

            # The visible count is a mirror of the rows, never a number of its
            # own — otherwise the card says 3 and the preview can only find 2.
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(PostComment)
                    .where(
                        PostComment.post_id == post.id,
                        PostComment.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            post.comment_count = int(count)

        await db.commit()
        print(f"Added {made_comments} comments.")

        # ---- reposts -------------------------------------------------------
        made_reposts = 0
        for prefix, handles in REPOSTS:
            post = next((p for p in posts if p.body.startswith(prefix)), None)
            if post is None:
                print(f"  post not found, skipping reposts: {prefix!r}")
                continue
            for handle in handles:
                author = people[handle.lower()]
                if await db.get(PostRepost, {"post_id": post.id, "user_id": author.id}) is None:
                    db.add(PostRepost(post_id=post.id, user_id=author.id))
                    made_reposts += 1
            await db.flush()

            # Same mirror rule as comments: the count is the rows, not a number
            # kept somewhere else that can drift away from them.
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(PostRepost)
                    .where(PostRepost.post_id == post.id)
                )
            ).scalar_one()
            post.repost_count = int(count)

        await db.commit()
        print(f"Added {made_reposts} reposts.")

        total_stories = (await db.execute(select(func.count()).select_from(Story))).scalar_one()
        total_comments = (
            await db.execute(select(func.count()).select_from(PostComment))
        ).scalar_one()
        total_reposts = (
            await db.execute(select(func.count()).select_from(PostRepost))
        ).scalar_one()
        print(
            f"Now: {total_stories} stories, {total_comments} comments, "
            f"{total_reposts} reposts."
        )

    await engine.dispose()
    print("\nLook at: /   (rail, comment previews)   /@bastilluxeapparel   /@studentuser")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed stories and comments (dev only).")
    parser.add_argument("--reset", action="store_true", help="delete existing rows first")
    args = parser.parse_args()
    asyncio.run(main(args.reset))
