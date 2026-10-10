"""Session repository — thin data-access layer over the sessions table."""

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.repositories.base import BaseRepository


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class SessionRepository(BaseRepository[Session]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Session)

    async def get_by_raw_token(self, raw_token: str) -> Session | None:
        token_hash = hash_session_token(raw_token)
        stmt = select(Session).where(Session.session_token_hash == token_hash)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
