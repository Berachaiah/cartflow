"""
User repository: signup-time lookups and creation.

Per PRD Chapter 3 sec 4 (username rules) and sec 8/9 (password + email
verification): usernames are case-insensitive (matched via
username_normalized), uniqueness is checked before creation, and account
creation always lands in PENDING_VERIFICATION status — verification is a
separate step (Chapter 3 sec 9), not handled here.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, User)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username_normalized(self, username_normalized: str) -> User | None:
        stmt = select(User).where(
            User.username_normalized == username_normalized, User.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_google_sub(self, google_sub: str) -> User | None:
        """Look up a returning Google user by their stable Google subject id.
        Matched BEFORE email at callback time, so a user who later changes
        their Google email still resolves to the same CartFlow account."""
        stmt = select(User).where(
            User.google_sub == google_sub, User.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        return await self.get_by_email(email) is not None

    async def username_exists(self, username_normalized: str) -> bool:
        return await self.get_by_username_normalized(username_normalized) is not None
