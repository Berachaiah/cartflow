"""Create (or repair) the operator account used by /admin.

WHY A SCRIPT AND NOT A SIGNUP FLOW. Staff accounts must not be creatable from
the public form, and a flag that can be set by anyone who can reach a route is
not a flag. This runs on a machine with database access, next to the migrations.

WHY THE PASSWORD IS A KNOWN DEFAULT. The first credential has to come from
somewhere, and printing a random one into a deployment log is worse than a
documented default the operator is told to change. /admin/account refuses to keep
it: the dashboard shows a banner until the password is no longer the default, and
the form is the first thing in the page.

    python scripts/seed_admin.py                     # cartflow / cartflow
    python scripts/seed_admin.py --username ada --password 'long-secret'

The script is idempotent: running it against an existing `cartflow` account
promotes it and (only if --password was passed explicitly) resets the password.
It never demotes anyone and never deletes anything.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.session import connect_args_for  # noqa: E402
from app.models.user import AccountStatus, AccountType, User  # noqa: E402

DEFAULT_USERNAME = "cartflow"
DEFAULT_PASSWORD = "cartflow"


async def main(username: str, password: str | None) -> int:
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL, connect_args=connect_args_for(settings.DATABASE_URL)
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        user = (
            await db.execute(
                select(User).where(User.username_normalized == username.lower())
            )
        ).scalar_one_or_none()

        if user is None:
            user = User(
                username=username,
                username_normalized=username.lower(),
                display_name="CartFlow Ops",
                full_name="CartFlow Operations",
                email=f"{username}@cartflow.local",
                account_type=AccountType.INDIVIDUAL,
                account_status=AccountStatus.ACTIVE,
                is_admin=True,
                is_seller=False,
                password_hash=hash_password(password or DEFAULT_PASSWORD),
            )
            db.add(user)
            print(f"created admin @{username}")
        else:
            user.is_admin = True
            # An account seeded before verification existed may still be
            # pending; staff must be able to sign in immediately.
            if user.account_status != AccountStatus.ACTIVE:
                user.account_status = AccountStatus.ACTIVE
                print(f"activated @{username}")
            if password:
                user.password_hash = hash_password(password)
                print(f"password reset for @{username}")
            print(f"promoted existing account @{username}")

        await db.commit()

    await engine.dispose()
    if not password:
        print(f"username: {username}\npassword: {DEFAULT_PASSWORD}  (change it in /admin/account)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote the CartFlow admin account.")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.username, args.password)))
