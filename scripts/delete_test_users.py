"""
One-off cleanup: deletes test/throwaway user accounts created while
testing the signup + email verification flow, along with their
verification_tokens rows (FK would otherwise block the user delete).

Uses hard delete, not soft delete — these are throwaway test rows,
not real user data that needs recovery.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, delete

from app.models.user import User
from app.models.verification_token import VerificationToken
from app.database.session import session_scope

USERNAMES_TO_DELETE = [
    "berachaiah02",
]


async def cleanup():
    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.username.in_(USERNAMES_TO_DELETE))
        )
        users = result.scalars().all()

        if not users:
            print("No matching test users found.")
            return

        for user in users:
            await session.execute(
                delete(VerificationToken).where(VerificationToken.user_id == user.id)
            )
            print(f"Deleted verification tokens for {user.username} ({user.email})")

        for user in users:
            await session.delete(user)
            print(f"Deleted user: {user.username} ({user.email})")

        print(f"\nCleaned up {len(users)} test account(s)")


if __name__ == "__main__":
    asyncio.run(cleanup())
