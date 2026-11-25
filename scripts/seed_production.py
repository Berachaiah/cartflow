"""
Production seeder — the catalogue, feed and rail a walkthrough shows, on the live site.

WHY THIS EXISTS. The stories/comments/reposts code was deployed against a
database holding three users and nothing else, so the live home page rendered an
empty feed and "No stories yet today" while every local check passed. The code
had shipped; the content had not. This is the content step.

NOT A SECOND COPY OF THE DEMO. The products, posts, stories, comments and
reposts are imported from `seed_products.py`, `seed_posts.py` and
`seed_social.py` — the same lists reviewed locally. If production kept its own
transcription, the two demos would drift and the thing being shown would stop
being the thing that was tested.

IMPORT ORDER IS LOAD-BEARING. Those modules assign the SQLite preview URL to
`os.environ` at import time, which is how they refuse to touch production. This
file therefore imports `app.database.session` FIRST: the engine is built from
`.env` when that module is first imported, so by the time the seeders run their
environment write lands on an engine that already exists. The guard then refuses
to continue unless that engine is the Postgres in `.env` — if the ordering were
ever broken, the script stops instead of quietly seeding a local SQLite file.

WHAT IT WRITES, in dependency order: missing demo accounts, their shops, the
listings, the feed posts and their likes, the stories with real likes and views,
then comments and reposts. `comment_count` and `repost_count` are recounted from
the rows after insertion rather than taken from a list — the same invariant the
services maintain, so a card cannot claim a count its own API cannot fill.

SAFETY. It demands `--confirm` and prints the target host before writing,
because there is no staging environment between this script and the live
database. It is idempotent by natural key (handle, product slug, a post's first
line, story author + caption, comment post + author + body, repost post +
author), so a second run adds nothing. There is deliberately no `--reset`: on a
live database "clear and rebuild" is one keystroke from a wiped demo feed and
there is nothing here worth that risk. It never updates an account that already
exists, so a real user's profile and password are left alone.

The demo accounts it creates sign in with the same DEFAULT_PASSWORD the dev
seeders use. That is a walkthrough credential, not a secret — rotate it or
remove those accounts wherever the site is more than a demo.

Run:
    ./.venv/Scripts/python.exe scripts/seed_production.py --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Imported before the dev seeders, on purpose: see the import note above.
from app.database.session import engine  # noqa: E402

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

import app.models  # noqa: F401,E402  — registers every mapper before use
from app.core.security import hash_password  # noqa: E402
from app.models.organization import (  # noqa: E402
    Organization,
    OrganizationStatus,
    OrganizationType,
)
from app.models.post import Post, PostComment, PostLike, PostRepost  # noqa: E402
from app.models.product import Product, ProductStatus  # noqa: E402
from app.models.story import Story, StoryLike, StoryView  # noqa: E402
from app.models.user import AccountStatus, AccountType, User  # noqa: E402

# The reviewed content. Importing these runs each module's top level (a URL
# assignment and class/constant definitions), never its `main`.
import seed_posts  # noqa: E402
import seed_products  # noqa: E402
import seed_social  # noqa: E402

# The like pairs `seed_posts` uses, restated because it keeps them inside its own
# `main()`. Same accounts, so the feed's Liked tab agrees with the cards.
POST_LIKE_PAIRS = [
    ("studentuser", "bastilluxeapparel"),
    ("studentuser", "mbl.label"),
    ("studentuser", "thebest"),
    ("thebest", "elexandco"),
    ("thebest", "studentuser"),
]

# Accounts that are people rather than shops, so a campus post does not look
# like it was written by a business.
PEOPLE = {
    "studentuser": {"display_name": "Student User", "account_type": AccountType.STUDENT},
}


def _host() -> str:
    url = engine.url
    return f"{url.host}:{url.port or 5432}/{url.database}"


async def _ensure_account(db, handle: str, password: str) -> tuple[User, bool]:
    """Fetch the account, or create the demo one. Returns (user, created)."""
    existing = (
        await db.execute(
            select(User).where(User.username_normalized == handle.lower())
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    spec = next(
        (b for b in seed_products.BRANDS if b["username"].lower() == handle.lower()),
        None,
    )
    person = PEOPLE.get(handle.lower(), {})
    user = User(
        email=f"{handle.replace('.', '')}@cartflow.demo",
        password_hash=hash_password(password),
        username=handle,
        username_normalized=handle.lower(),
        display_name=spec["display_name"] if spec else person.get("display_name", handle),
        bio=spec["bio"] if spec else None,
        account_type=(
            AccountType.BUSINESS
            if spec
            else person.get("account_type", AccountType.INDIVIDUAL)
        ),
        account_status=AccountStatus.ACTIVE,
        is_seller=bool(spec),
    )
    db.add(user)
    await db.flush()
    return user, True


async def main(password: str) -> None:
    if not engine.url.drivername.startswith("postgresql"):
        sys.exit(
            f"Refusing to seed: the engine points at {engine.url.drivername}, "
            "not the Postgres in .env."
        )

    print(f"Target: {_host()}")
    now = datetime.now(timezone.utc)
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with Session() as db:
        # ---- 1. accounts ---------------------------------------------------
        handles: set[str] = {b["username"] for b in seed_products.BRANDS}
        handles |= {p[0] for p in seed_posts.POSTS}
        handles |= {s[0] for s in seed_social.STORIES}
        handles |= {h for _, rows in seed_social.COMMENTS for h, _, _ in rows}
        handles |= {h for _, hs in seed_social.REPOSTS for h in hs}
        for likes in seed_social.STORY_LIKERS.values():
            handles |= set(likes)
        handles |= set(seed_social.STORY_VIEWERS)

        people: dict[str, User] = {}
        created_accounts = 0
        for handle in sorted(handles):
            user, created = await _ensure_account(db, handle, password)
            people[handle.lower()] = user
            created_accounts += int(created)
        await db.commit()
        print(f"Accounts: {created_accounts} created, {len(people)} present.")

        # ---- 2. shops and listings ----------------------------------------
        sme_id = (
            await db.execute(
                select(OrganizationType.id)
                .where(OrganizationType.slug == "sme")
                .limit(1)
            )
        ).scalar_one_or_none()
        if sme_id is None:
            sys.exit(
                "No 'sme' organization type in this database. Seed the taxonomy "
                "before adding shops."
            )

        made_shops = made_products = 0
        for spec in seed_products.BRANDS:
            user = people[spec["username"].lower()]
            org = (
                await db.execute(
                    select(Organization).where(Organization.owner_user_id == user.id)
                )
            ).scalar_one_or_none()
            if org is None:
                org = (
                    await db.execute(
                        select(Organization).where(Organization.slug == spec["slug"])
                    )
                ).scalar_one_or_none()
            if org is None:
                org = Organization(
                    official_name=spec["shop"],
                    short_name=spec["shop"],
                    slug=spec["slug"],
                    country="Nigeria",
                    state=spec["state"],
                    status=OrganizationStatus.ACTIVE.value,
                    organization_type_id=sme_id,
                    owner_user_id=user.id,
                    pickup_address=spec["pickup"],
                )
                db.add(org)
                await db.flush()
                made_shops += 1
            elif org.owner_user_id is None:
                # A curated row with no owner: adopt it rather than orphan a shop.
                org.owner_user_id = user.id

            org.pickup_address = spec["pickup"]
            org.short_name = spec["shop"]

            for item in spec["products"]:
                existing = (
                    await db.execute(select(Product).where(Product.slug == item["slug"]))
                ).scalar_one_or_none()
                payload = {
                    **item,
                    "organization_id": org.id,
                    "delivery_areas": spec["delivery"],
                    "pickup_address": spec["pickup"],
                    "status": ProductStatus.ACTIVE.value,
                }
                if existing is None:
                    db.add(Product(**payload))
                    made_products += 1
                else:
                    # Upsert on purpose: a re-run applies copy and photo fixes.
                    for field, value in payload.items():
                        setattr(existing, field, value)
        await db.commit()
        print(f"Shops: {made_shops} created. Listings: {made_products} created.")

        # ---- 3. the feed ---------------------------------------------------
        made_posts = 0
        for handle, hours_ago, badge, location, body, images, slugs, likes in (
            seed_posts.POSTS
        ):
            first_line = body.split("\n")[0]
            exists = (
                await db.execute(select(Post).where(Post.body.like(f"{first_line}%")))
            ).scalar_one_or_none()
            if exists is not None:
                continue
            author = people[handle.lower()]
            created = now - timedelta(hours=hours_ago)
            db.add(
                Post(
                    author_id=author.id,
                    body=body,
                    images=[{"src": src, "alt": alt} for src, alt in images],
                    tagged_product_slugs=slugs,
                    badge=badge,
                    location=location,
                    like_count=likes,
                    comment_count=0,
                    repost_count=0,
                    created_at=created,
                    updated_at=created,
                )
            )
            made_posts += 1
        await db.flush()

        made_likes = 0
        for liker_handle, author_handle in POST_LIKE_PAIRS:
            liker = people[liker_handle.lower()]
            author = people[author_handle.lower()]
            for post in (
                await db.execute(select(Post).where(Post.author_id == author.id))
            ).scalars().all():
                if await db.get(PostLike, {"post_id": post.id, "user_id": liker.id}) is None:
                    db.add(PostLike(post_id=post.id, user_id=liker.id))
                    post.like_count = (post.like_count or 0) + 1
                    made_likes += 1
        await db.commit()
        print(f"Posts: {made_posts} created. Likes: {made_likes} added.")

        posts = (await db.execute(select(Post))).scalars().all()

        # ---- 4. the story rail ---------------------------------------------
        made_stories = 0
        for handle, image, caption, slug, likes, views, hours_ago in (
            seed_social.STORIES
        ):
            author = people[handle.lower()]
            exists = (
                await db.execute(
                    select(Story).where(
                        Story.author_id == author.id, Story.caption == caption
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            created = now - timedelta(hours=hours_ago)
            db.add(
                Story(
                    author_id=author.id,
                    image_url=image,
                    caption=caption,
                    tagged_product_slug=slug,
                    like_count=likes,
                    view_count=views,
                    expires_at=None,  # demo content: has to survive the night
                    created_at=created,
                    updated_at=created,
                )
            )
            made_stories += 1
        await db.flush()

        made_story_likes = made_views = 0
        stories = (
            await db.execute(
                select(Story).where(Story.caption.in_([s[2] for s in seed_social.STORIES]))
            )
        ).scalars().all()
        for story in stories:
            author_handle = next(
                (
                    s[0].lower()
                    for s in seed_social.STORIES
                    if people[s[0].lower()].id == story.author_id
                ),
                None,
            )
            for liker_handle in seed_social.STORY_LIKERS.get(author_handle or "", []):
                liker = people[liker_handle.lower()]
                if await db.get(
                    StoryLike, {"story_id": story.id, "user_id": liker.id}
                ) is None:
                    db.add(StoryLike(story_id=story.id, user_id=liker.id))
                    story.like_count = (story.like_count or 0) + 1
                    made_story_likes += 1
            for viewer_handle in seed_social.STORY_VIEWERS:
                viewer = people[viewer_handle.lower()]
                if await db.get(
                    StoryView, {"story_id": story.id, "user_id": viewer.id}
                ) is None:
                    db.add(StoryView(story_id=story.id, user_id=viewer.id))
                    story.view_count = (story.view_count or 0) + 1
                    made_views += 1
        await db.commit()
        print(
            f"Stories: {made_stories} created, {made_story_likes} likes, "
            f"{made_views} views."
        )

        # ---- 5. comments ----------------------------------------------------
        made_comments = 0
        for prefix, rows in seed_social.COMMENTS:
            post = next((p for p in posts if p.body.startswith(prefix)), None)
            if post is None:
                print(f"  post not found, skipping comments: {prefix!r}")
                continue
            for handle, body, minutes_after in rows:
                author = people[handle.lower()]
                exists = (
                    await db.execute(
                        select(PostComment).where(
                            PostComment.post_id == post.id,
                            PostComment.author_id == author.id,
                            PostComment.body == body,
                            PostComment.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if exists is not None:
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
            # The visible count is the rows, never a number of its own.
            post.comment_count = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(PostComment)
                        .where(
                            PostComment.post_id == post.id,
                            PostComment.deleted_at.is_(None),
                        )
                    )
                ).scalar_one()
            )
        await db.commit()
        print(f"Comments: {made_comments} added.")

        # ---- 6. reposts -----------------------------------------------------
        made_reposts = 0
        for prefix, repost_handles in seed_social.REPOSTS:
            post = next((p for p in posts if p.body.startswith(prefix)), None)
            if post is None:
                print(f"  post not found, skipping reposts: {prefix!r}")
                continue
            for handle in repost_handles:
                author = people[handle.lower()]
                if await db.get(
                    PostRepost, {"post_id": post.id, "user_id": author.id}
                ) is None:
                    db.add(PostRepost(post_id=post.id, user_id=author.id))
                    made_reposts += 1
            await db.flush()
            post.repost_count = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(PostRepost)
                        .where(PostRepost.post_id == post.id)
                    )
                ).scalar_one()
            )
        await db.commit()
        print(f"Reposts: {made_reposts} added.")

        # ---- 7. what the live site now has ----------------------------------
        totals = {}
        for name, model in (
            ("users", User),
            ("products", Product),
            ("posts", Post),
            ("post_comments", PostComment),
            ("post_reposts", PostRepost),
            ("stories", Story),
            ("story_likes", StoryLike),
            ("story_views", StoryView),
        ):
            totals[name] = int(
                (await db.execute(select(func.count()).select_from(model))).scalar_one()
            )
        print("\nDatabase now holds:")
        for name, value in totals.items():
            print(f"  {name:16} {value}")

        zero_counts = (
            await db.execute(
                select(func.count())
                .select_from(Post)
                .where((Post.repost_count == 0) | (Post.comment_count == 0))
            )
        ).scalar_one()
        print(f"  posts whose comment or repost count is still 0: {zero_counts}")

    await engine.dispose()
    print("\nDemo logins (rotate if the site is public):")
    for handle in ("bastilluxeapparel", "mbl.label", "elexandco", "studentuser"):
        print(f"  @{handle:20} {password}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the production database.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="required: acknowledges that this writes to the database in .env",
    )
    parser.add_argument("--password", default=seed_products.DEFAULT_PASSWORD)
    args = parser.parse_args()

    if not args.confirm:
        sys.exit(
            f"This writes demo content to {_host()}. Re-run with --confirm if that "
            "is the environment you mean."
        )
    asyncio.run(main(args.password))
