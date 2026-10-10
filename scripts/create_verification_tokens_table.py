"""
One-off: creates the verification_tokens table in Supabase. Uses
Base.metadata.create_all, same pattern as the initial table setup —
this only creates tables that don't already exist, so it's safe to
rerun.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Base
from app.database.session import engine


async def create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("OK: verification_tokens table created (or already existed)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create())
