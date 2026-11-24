"""
Dev-only feed seeder — brand posts whose photos ARE their products.

WHY THIS REPLACES THE FIRST VERSION.

The first pass invented captions for one demo shop and used generic Unsplash
photos. That produced exactly the problem the product grid had: a post about
streetwear illustrated with a stock photo of something else, and a "jollof" post
whose picture was fufu.

The posts here belong to the four real labels (`scripts/seed_products.py` creates
their accounts and shops) and every photo is that brand's own product shot, taken
from their store — so a post and the product it tags cannot disagree about what
was sold. Captions stay short and brand-like: a drop, a restock, a styling note.
A post is not a product card: it should not repeat the full description or the
price list, because the tag is what links a post to the listing.

Authored by:
  @bastilluxeapparel  two campaign posts   (BX25 Jersey, Seraph T-Shirt)
  @mbl.label          two drop posts       (Midnight Skully, World Cup Tee)
  @elexandco          one jewellery post   (The Cipher Bracelet)
  @thebest            one campus post      (Campus Essential Hoodie)
  @studentuser        one food post        (Jollof Rice & Grilled Chicken)

SpaceWorm has no posts on purpose: spworm.xyz no longer resolves and Instagram
serves nothing to a signed-out fetch, so any photo attributed to them would be
invented. Their account and shop exist and are empty.

SAFETY. SQLite only. Idempotent by post body; `--reset` clears and rebuilds, which
is how a caption or photo gets replaced.

Run:
    ./.venv/Scripts/python.exe scripts/seed_posts.py --reset
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
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.database.session import engine  # noqa: E402
from app.models.post import Post, PostLike  # noqa: E402
from app.models.user import User  # noqa: E402

B = "/static/images/brands"
U = "https://images.unsplash.com/photo-"

# (author handle, hours ago, badge, location, body, [(src, alt)], tagged slugs, likes)
POSTS: list[tuple] = [
    (
        "bastilluxeapparel",
        3,
        "✨ New Drop",
        "Lekki, Lagos",
        "Drop 02 is live. The BX25 jersey in bubblegum pink — mesh body, contrast "
        "piping, our wordmark across the chest. Made to be worn loose.\n"
        "Available now on the shop. #Bastilluxe #Drop02",
        [(f"{B}/bastilluxe-bx25-jersey.jpg",
          "Pink Bastilluxe BX25 jersey")],
        ["bastilluxe-bx25-jersey"],
        1832,
    ),
    (
        "bastilluxeapparel",
        27,
        None,
        "Lekki, Lagos",
        "Seraph, restocked. Heavyweight black tee, small crest on the chest, boxy "
        "through the body. Same cut we sold out of last month — quietly, before "
        "anyone could post about it.\n"
        "Sizes M to XXL back on the shop.",
        [(f"{B}/bastilluxe-seraph-tee.jpg",
          "Black Bastilluxe Seraph t-shirt")],
        ["bastilluxe-seraph-tee"],
        2410,
    ),
    (
        "mbl.label",
        8,
        "🖤 Restock",
        "Yaba, Lagos",
        "Midnight Skully is back. Brushed cotton, embroidered script, sits snug "
        "without squeezing. Half the city has been asking — this is the restock.\n"
        "#MADEBYLUTHER #MBL",
        [(f"{B}/mbl-midnight-skully.webp",
          "Black Madebyluther skull cap")],
        ["mbl-midnight-skully"],
        967,
    ),
    (
        "mbl.label",
        31,
        "🏆 Heroes Are Made",
        "Yaba, Lagos",
        "Heroes Are Made. World Cup tee, front map print, the line across the back. "
        "Heavyweight cotton, so it hangs instead of clinging.\n"
        "Limited run — shop link in bio.",
        [(f"{B}/mbl-world-cup-tee.webp",
          "White Madebyluther World Cup tee, front and back")],
        ["mbl-world-cup-tee"],
        1508,
    ),
    (
        "elexandco",
        19,
        None,
        "Victoria Island, Lagos",
        "The Cipher. Silver-tone chain, black onyx, textured spacers that catch "
        "whatever light is in the room. Hand-finished in the studio, adjustable "
        "clasp.\n"
        "Now on Elex & Co.",
        [(f"{B}/elex-cipher-bracelet.jpg",
          "Silver chain bracelet with black onyx beads")],
        ["elex-cipher-bracelet"],
        742,
    ),
    (
        "thebest",
        44,
        "🔥 Trending",
        "Bells University",
        "Hoodie weather is back on campus. The Essential in grey, heavyweight "
        "fleece, no logo on the front — the one people buy in three colours.\n"
        "Pickup at Faculty Road or delivery to your hostel.",
        [(f"{U}1556821840-3a63f95609a7?q=80&w=900&auto=format&fit=crop",
          "Grey Campus Essential hoodie folded on a plain background")],
        ["campus-essential-hoodie"],
        2847,
    ),
    (
        "studentuser",
        6,
        "🛵 25-35 min",
        "Bells University Gate",
        "Lunch sorted. Party jollof, grilled chicken, plantain on the side. They "
        "cook in batches from 11, so it is still hot when it reaches the hostel.\n"
        "#CampusEats",
        [("/static/images/products/jollof-rice-combo.jpg",
          "Plate of jollof rice with grilled chicken and plantain")],
        ["jollof-rice-combo"],
        1204,
    ),
]


async def main(reset: bool) -> None:
    if not os.environ["DATABASE_URL"].startswith("sqlite"):
        sys.exit("Refusing to seed a non-SQLite database.")

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)

    async with Session() as db:
        people = {
            u.username.lower(): u
            for u in (await db.execute(select(User))).scalars().all()
        }
        missing = {handle for handle, *_ in POSTS if handle.lower() not in people}
        if missing:
            sys.exit(
                f"Missing accounts: {sorted(missing)}. "
                "Run scripts/seed_products.py first — it creates the brand shops."
            )

        if reset:
            await db.execute(delete(PostLike))
            await db.execute(delete(Post))
            await db.commit()
            print("Reset: removed every post and like.")

        added = 0
        for handle, hours_ago, badge, location, body, images, slugs, likes in POSTS:
            first_line = body.split("\n")[0]
            exists = (
                await db.execute(select(Post).where(Post.body.like(f"{first_line}%")))
            ).scalar_one_or_none()
            if exists is not None:
                continue

            author = people[handle.lower()]
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
                    created_at=now - timedelta(hours=hours_ago),
                    updated_at=now - timedelta(hours=hours_ago),
                )
            )
            added += 1

        await db.commit()
        total = (await db.execute(select(Post))).scalars().all()
        print(f"Added {added} posts; {len(total)} in the table now.")

        # Real likes from real accounts, so the Liked tab and the like counts
        # agree. Pairs are (liker, author): the buyer follows the brands.
        pairs = [
            ("studentuser", "bastilluxeapparel"),
            ("studentuser", "mbl.label"),
            ("studentuser", "thebest"),
            ("thebest", "elexandco"),
            ("thebest", "studentuser"),
        ]
        made = 0
        for liker_handle, author_handle in pairs:
            liker = people.get(liker_handle.lower())
            author = people.get(author_handle.lower())
            if liker is None or author is None:
                continue
            posts = (
                await db.execute(select(Post).where(Post.author_id == author.id))
            ).scalars().all()
            for post in posts:
                existing = await db.get(
                    PostLike, {"post_id": post.id, "user_id": liker.id}
                )
                if existing is None:
                    db.add(PostLike(post_id=post.id, user_id=liker.id))
                    post.like_count = (post.like_count or 0) + 1
                    made += 1
        await db.commit()
        print(f"Added {made} likes across those posts.")

    await engine.dispose()
    print("\nLook at: /   /@bastilluxeapparel   /@mbl.label   /@elexandco   /@thebest")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the demo feed (dev only).")
    parser.add_argument("--reset", action="store_true", help="delete existing posts first")
    args = parser.parse_args()
    asyncio.run(main(args.reset))
