"""
Dev-only demo seeder — makes every screen in a walkthrough have something real in it.

WHY THIS EXISTS. The preview database had three accounts and eight products but
**zero** follow edges and **zero** conversations. Three things then look broken in
a demo even though the code is right:

  - `/messages` renders an empty inbox, and the compose picker is scoped to the
    follow graph — so with no follows you cannot start a thread from the UI at
    all. Messaging was undemonstrable, not merely empty.
  - `/notifications` is built on `user_follows`, so it was empty too.
  - The only seller account (`TheBest`, who owns the org behind all eight
    products) was created by hand, so nobody knew its password — meaning the
    Business Hub had no login that could open it.

WHAT IT DOES, in order:

  1. **Gives the seller a known password.** Without this the Hub cannot be shown
     at all. It keeps the account's existing status; V1 lets PENDING_VERIFICATION
     users log in, so nothing else needs changing.
  2. **Builds the follow graph**, both ways, so the compose picker is populated
     and the notification inbox has rows.
  3. **Sends one real conversation** through `messaging_service.send_message` —
     the same function the API calls, so the thread obeys §6 exactly: it opens
     PENDING on the first message, flips to ACCEPTED when the other side replies,
     and every mirror column (`last_message_*`) is written by the one writer that
     owns them. No rows are fabricated here; that is the difference between a
     seeded demo and a fake one.
  4. **Turns the 48h disappearing timer OFF for that thread** and clears the
     `expires_at` the sends stamped on its messages.

     This is the step that matters for a competition. Disappearing is ON by
     default, so a thread seeded today is gone two days later — the reason the
     earlier social seeder refused to seed conversations at all. Off, the sample
     thread survives until someone deletes it, and turning the timer back on is
     one tap in the thread header, which is itself worth showing.

SAFETY. Refuses to run against anything but SQLite: `.env` points at the live
Supabase Postgres, and writing demo users and messages into a production database
is not a mistake worth making once. Idempotent — re-running sets the password
again, adds only missing follows, and does not duplicate the thread.

Run:
    ./venv/bin/python scripts/seed_demo.py
    ./venv/bin/python scripts/seed_demo.py --password 'Something-else-2026'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Before app.core.config is imported, and not `setdefault` on the .env value:
# this script's target is the preview file, always.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./dev_preview.db"

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.models.conversation import Conversation, Message  # noqa: E402
from app.models.user import User, UserFollow  # noqa: E402
from app.services import messaging as messaging_service  # noqa: E402

# The seller who owns the org behind the seeded products, and the buyer account
# the demo signs in with. Two sides, so a live exchange can be shown happening.
SELLER_USERNAME = "thebest"
BUYER_USERNAME = "studentuser"
DEFAULT_PASSWORD = "Preview-pass-2026"

# The thread, in order: (sender username, body). Two full sentences from each
# side are enough to show bubbles on both sides, a timestamp group and a preview
# line in the inbox — and short enough to stay realistic.
THREAD: list[tuple[str, str]] = [
    (BUYER_USERNAME, "Hi! Is the Campus Essential Hoodie still available in a large?"),
    (SELLER_USERNAME, "Yes it is 🙌 Large is in stock and it ships same day."),
    (BUYER_USERNAME, "Nice. Can I pick it up at the gate instead of paying delivery?"),
    (SELLER_USERNAME, "Of course — pickup at YWC Technologies, 9am to 6pm."),
    (BUYER_USERNAME, "Perfect, I'll come by tomorrow morning. Thanks!"),
    (SELLER_USERNAME, "Noted. I'll keep one aside for you 👍"),
]


async def _user(db, username: str) -> User | None:
    return (
        await db.execute(
            select(User).where(User.username_normalized == username.lower())
        )
    ).scalar_one_or_none()


async def _follow(db, *, follower: User, following: User) -> bool:
    """Insert one follow edge if absent. Returns True when it was added."""
    existing = (
        await db.execute(
            select(UserFollow).where(
                UserFollow.follower_id == follower.id,
                UserFollow.following_id == following.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(UserFollow(follower_id=follower.id, following_id=following.id))
    return True


async def seed(password: str) -> None:
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with Session() as db:
        seller = await _user(db, SELLER_USERNAME)
        buyer = await _user(db, BUYER_USERNAME)
        if seller is None or buyer is None:
            sys.exit(
                f"Expected both @{SELLER_USERNAME} and @{BUYER_USERNAME} to exist. "
                "Run scripts/dev_preview_seed.py first, then re-run this."
            )

        # --- 1. a seller login that can actually open the Business Hub --------
        seller.password_hash = hash_password(password)
        # COMMITTED HERE, on its own, before anything else touches the session.
        # `send_message` below manages its own transactions (including a SAVEPOINT
        # around the conversation insert), and a pending change left open across
        # those was silently discarded: the script printed "Password set", the
        # hash in the database was still the old one, and login failed with 401.
        # One commit now, rather than one mystery later.
        await db.commit()
        print(f"Password set for @{seller.username} ({seller.account_status}).")

        # --- 2. the follow graph --------------------------------------------
        added = sum(
            [
                await _follow(db, follower=seller, following=buyer),
                await _follow(db, follower=buyer, following=seller),
            ]
        )
        await db.flush()
        print(f"Follow edges added: {added} (both directions exist either way).")

        # --- 3. one real conversation ---------------------------------------
        existing = (
            await db.execute(
                select(Conversation).where(
                    Conversation.pair_key
                    == messaging_service.pair_key(seller.id, buyer.id)
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            conversation = existing
            print(f"Thread already exists ({existing.status}); not sending again.")
        else:
            people = {BUYER_USERNAME: buyer, SELLER_USERNAME: seller}
            conversation = None
            for sender_name, body in THREAD:
                sender = people[sender_name]
                result = await messaging_service.send_message(
                    db,
                    sender=sender,
                    username=(SELLER_USERNAME if sender is buyer else BUYER_USERNAME),
                    body=body,
                )
                conversation = result.conversation
            print(f"Sent {len(THREAD)} messages; thread is {conversation.status}.")

        # --- 4. make it survive past this week ------------------------------
        conversation.disappear_after_seconds = None
        await db.execute(
            update(Message)
            .where(Message.conversation_id == conversation.id)
            .values(expires_at=None)
        )
        await db.flush()
        await db.commit()

        total = (
            await db.execute(
                select(Message).where(Message.conversation_id == conversation.id)
            )
        ).scalars().all()
        print(f"Disappearing off for this thread; {len(total)} messages are permanent.")

    await engine.dispose()

    print("\nWhat to demo:")
    print(f"  /messages             @{BUYER_USERNAME} - one thread, unread row")
    print(f"  /@{SELLER_USERNAME}          follow counts are real now")
    print("  /notifications        rows from the follow graph")
    print("  /dashboard            sign in as the seller to see the Business Hub")
    print(f"\n  buyer  : {BUYER_USERNAME} / {password}")
    print(f"  seller : {SELLER_USERNAME} / {password}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo content (dev only).")
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    url = os.environ["DATABASE_URL"]
    if not url.startswith("sqlite"):
        sys.exit(f"Refusing to seed a non-SQLite database ({url.split('://')[0]}).")

    await seed(args.password)


if __name__ == "__main__":
    asyncio.run(main())
