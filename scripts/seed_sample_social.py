"""
Dev-only social seeder — gives one account followers so the social pages have
something in them.

WHY THIS EXISTS. /notifications and the profile's follower counts read the real
`user_follows` table, so on a fresh preview database they are honestly empty.
That is correct behaviour and useless for looking at the page. This inserts
sample accounts and follow edges so the Activity inbox, the follower/following
counts and the Follow-back button can be seen working.

WHAT IT CANNOT SEED, and why not:

  - **Conversations.** The tables exist now (`conversations`,
    `conversation_participants`, `messages`) and rows could be inserted, so this
    is a choice rather than an empty schema. Two reasons not to. A seeded thread
    puts sentences in a sample account's mouth and the inbox cannot tell them from
    real ones — and disappearing messages are ON by default at 48 hours, so
    anything seeded quietly evaporates two days later and the next person to look
    finds an inbox that was full on Monday and empty on Wednesday.

    What this script DOES do for /messages is the part that matters: the compose
    picker is scoped to the follow graph, so every mutual below shows up in it and
    a real conversation is two taps away. That is a better demo than a fake one.
  - **Posts, products, orders, events.** No tables yet, so the same words that used
    to apply to messages still apply to these. The home feed's posts are a Jinja
    literal in `home.html`, not rows.

So the social graph is the only part of the app that can be filled with real
data today, and it is the part /notifications is built on — and now the part the
message picker reads too.

SAFETY. Sample accounts are written with `@sample.cartflow.test` emails and no
password hash: they cannot be logged into, and `--undo` can find every one of
them exactly. The script REFUSES to run against a non-SQLite database, because
`.env` points at the live Supabase Postgres and seeding fake followers into it
is not a mistake worth making once.

Run:
    ./venv/bin/python scripts/seed_sample_social.py
    ./venv/bin/python scripts/seed_sample_social.py --email someone@else.com
    ./venv/bin/python scripts/seed_sample_social.py --undo
"""

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Before app.core.config is imported, and deliberately not `setdefault` on a
# value read from .env: this script's target is the preview file, always.
os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///./dev_preview.db"
)

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database.session import AsyncSessionLocal, dispose_engine, engine  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import AccountStatus, AccountType, User, UserFollow  # noqa: E402

DEFAULT_EMAIL = "berachaiah.abolaji@gmail.com"

# The marker that makes --undo exact. A reserved TLD, so it can never collide
# with an address a real person could sign up with.
SAMPLE_DOMAIN = "sample.cartflow.test"

# 24 followers rather than a tidy 10: the Activity window is 20 rows, so this is
# the only way to see "Show more (20 of 24)" and the ?show=40 link do their job.
#
# `ago` spreads the follow timestamps across every branch of time_ago() — under a
# minute, minutes, hours, days, weeks, and two past the five-week cutoff where it
# switches to a date. That ladder is otherwise only checked in tests, and this is
# the screen it was written for.
#
# `school` — True: a schoolmate at the target's own university, so the row's
# affiliation line matches theirs. False: a different school, chosen from the
# real organizations table. None: no affiliation at all, which must also render.
SAMPLES = [
    # username        display name          ago                     school seller bio
    ("adaezeokonkwo", "Adaeze Okonkwo",     timedelta(seconds=20),  True,  False, "Final year Computer Science. Selling my textbooks."),
    ("chidieze",      "Chidi Eze",          timedelta(minutes=8),   True,  True,  "Sneakers and streetwear. Delivery on campus."),
    ("ngoziibe",      "Ngozi Ibe",          timedelta(minutes=41),  True,  False, None),
    ("tundebakare",   "Tunde Bakare",       timedelta(hours=2),     True,  True,  "Print Hub — projects, ID cards, lamination."),
    ("aishabello",    "Aisha Bello",        timedelta(hours=5),     True,  False, "Microbiology. Ask me about lab coats."),
    ("emekanwosu",    "Emeka Nwosu",        timedelta(hours=9),     False, False, None),
    ("funmilayoade",  "Funmilayo Adeyemi",  timedelta(hours=20),    True,  False, "Law. Debate society."),
    ("kelechiobi",    "Kelechi Obi",        timedelta(days=1),      False, True,  "Phone accessories, chargers, cases."),
    ("halimayusuf",   "Halima Yusuf",       timedelta(days=1, hours=6), True, False, None),
    ("obiorachukwu",  "Obiora Chukwu",      timedelta(days=2),      True,  False, "Engineering. Fixing laptops on the side."),
    ("zainabmusa",    "Zainab Musa",        timedelta(days=3),      False, False, None),
    ("segunolatunji", "Segun Olatunji",     timedelta(days=4),      True,  True,  "Thrift plug. New drops every Friday."),
    ("blessingeze",   "Blessing Eze",       timedelta(days=5),      True,  False, None),
    ("ibrahimsani",   "Ibrahim Sani",       timedelta(days=6),      False, False, "Mass Comm. Campus photographer."),
    ("chiomanwankwo", "Chioma Nwankwo",     timedelta(days=8),      True,  False, None),
    ("yusufabdulahi", "Yusuf Abdulahi",     timedelta(days=11),     True,  True,  "Groceries and provisions, hostel delivery."),
    ("amakaugo",      "Amaka Ugo",          timedelta(days=15),     False, False, None),
    ("davidojo",      "David Ojo",          timedelta(days=19),     True,  False, "Accounting. Chelsea."),
    ("ruthadeleke",   "Ruth Adeleke",       timedelta(days=23),     True,  False, None),
    ("musaibrahim",   "Musa Ibrahim",       timedelta(days=27),     False, True,  "Barbing salon, Block C."),
    ("gracealabi",    "Grace Alabi",        timedelta(days=31),     True,  False, None),
    ("peterokafor",   "Peter Okafor",       timedelta(days=33),     True,  False, "Pharmacy."),
    ("hauwaadamu",    "Hauwa Adamu",        timedelta(days=48),     True,  False, None),   # past 5 weeks — shows a date
    ("olumideani",    "Olumide Ani",        timedelta(days=95),     False, False, None),   # older still
]

# Which of the samples the target follows BACK. These render "Following" instead
# of "Follow back", which is the state most likely to be broken without anyone
# noticing — a wrong label there turns the button into an unfollow.
MUTUAL = {"chidieze", "tundebakare", "kelechiobi", "funmilayoade", "segunolatunji", "davidojo"}


def _guard_sqlite() -> None:
    url = str(engine.url)
    if not url.startswith("sqlite"):
        # Deliberately does not print the URL: it carries the Postgres password.
        sys.exit(
            "REFUSING TO RUN: DATABASE_URL is not SQLite.\n"
            "This seeder inserts fake accounts and is for ./dev_preview.db only.\n"
            "Run scripts/dev_preview.sh, or set DATABASE_URL to the preview file."
        )


async def _target(db: AsyncSession, email: str) -> User:
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        sys.exit(
            f"No account with email {email} in this database.\n"
            "Sign up through the preview server first, or pass --email."
        )
    return user


async def _sample_ids(db: AsyncSession) -> list[uuid.UUID]:
    rows = await db.execute(
        select(User.id).where(User.email.like(f"%@{SAMPLE_DOMAIN}"))
    )
    return list(rows.scalars())


async def undo(db: AsyncSession) -> None:
    ids = await _sample_ids(db)
    if not ids:
        print("Nothing to undo — no sample accounts in this database.")
        return
    # Edges first: user_follows has FKs pointing at both ends, and a sample
    # account can be on either side of one (the target follows some of them back).
    await db.execute(
        delete(UserFollow).where(
            UserFollow.follower_id.in_(ids) | UserFollow.following_id.in_(ids)
        )
    )
    await db.execute(delete(User).where(User.id.in_(ids)))
    await db.commit()
    print(f"Removed {len(ids)} sample accounts and every follow edge touching them.")


async def seed(db: AsyncSession, email: str) -> None:
    target = await _target(db, email)
    existing = await _sample_ids(db)
    if existing:
        sys.exit(
            f"{len(existing)} sample accounts are already here. Run with --undo first "
            "if you want a clean set — seeding twice would only add duplicate names."
        )

    # Other schools, from the real taxonomy rather than invented, so an
    # affiliation line reads like every other one in the app.
    others = list(
        (
            await db.execute(
                select(Organization)
                .where(
                    Organization.status == "active",
                    Organization.short_name.isnot(None),
                    Organization.id != target.organization_id,
                )
                .limit(8)
            )
        ).scalars()
    )

    now = datetime.now(timezone.utc)
    made = 0

    for i, (username, display_name, ago, schoolmate, seller, bio) in enumerate(SAMPLES):
        if schoolmate:
            org_id = target.organization_id
        elif others:
            org_id = others[i % len(others)].id
        else:
            org_id = None

        user = User(
            account_type=AccountType.STUDENT if org_id else AccountType.INDIVIDUAL,
            # ACTIVE deliberately: list_followers hides suspended and soft-deleted
            # accounts, so a PENDING_VERIFICATION sample would insert a row that
            # never renders and look like a broken query.
            account_status=AccountStatus.ACTIVE,
            email=f"{username}@{SAMPLE_DOMAIN}",
            password_hash=None,          # cannot be logged into
            username=username,
            username_normalized=username.lower(),
            display_name=display_name,
            full_name=display_name,
            bio=bio,
            organization_id=org_id,
            is_seller=seller,
        )
        db.add(user)
        await db.flush()

        followed_at = now - ago
        db.add(
            UserFollow(
                follower_id=user.id,
                following_id=target.id,
                created_at=followed_at,
                updated_at=followed_at,
            )
        )
        if username in MUTUAL:
            # Followed back a little after they followed — which is how it happens.
            back = followed_at + timedelta(minutes=7)
            db.add(
                UserFollow(
                    follower_id=target.id,
                    following_id=user.id,
                    created_at=min(back, now),
                    updated_at=min(back, now),
                )
            )
        made += 1

    await db.commit()

    print(f"Seeded {made} followers for @{target.username} ({email}).")
    print(f"  {len(MUTUAL)} of them are mutual, so those rows read 'Following'.")
    print(f"  {made - len(MUTUAL)} read 'Follow back'.")
    print("\nWhat to look at:")
    print("  /notifications   20 rows, then 'Show more (20 of 24)' -> ?show=40")
    print("                   timestamps run from 'now' through '4w' to a date")
    print(f"  /@{target.username}       follower and following counts are real now")
    print("  /messages        no threads seeded on purpose, but the compose picker reads")
    print(f"                   this follow graph — the {len(MUTUAL)} mutuals are all in it, and")
    print("                   a real conversation is two taps away")
    print("\nUndo:  ./venv/bin/python scripts/seed_sample_social.py --undo")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="account to give followers to")
    parser.add_argument("--undo", action="store_true", help="remove every sample account")
    args = parser.parse_args()

    _guard_sqlite()
    async with AsyncSessionLocal() as db:
        if args.undo:
            await undo(db)
        else:
            await seed(db, args.email)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
