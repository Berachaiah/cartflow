"""One-off: Nile University, Abuja is Private, FCT — not yet in the reference CSV."""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope


async def set_type():
    async with session_scope() as session:
        result = await session.execute(
            select(University).where(University.official_name == "Nile University")
        )
        uni = result.scalar_one_or_none()

        if uni is None:
            print("No row found named 'Nile University' — nothing changed.")
            return

        uni.institution_type = "private"
        uni.state = "Federal Capital Territory"
        uni.status = "active"
        print(f"Set institution_type=private, state=FCT for 'Nile University' (id={uni.id})")


if __name__ == "__main__":
    asyncio.run(set_type())
