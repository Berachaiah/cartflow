"""
One-off rename: the generic "Federal University" row (state=Kaduna) is
Federal University of Education, Zaria — formerly Federal College of
Education, Zaria, upgraded to full university status.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope


async def rename():
    async with session_scope() as session:
        result = await session.execute(
            select(University).where(University.official_name == "Federal University")
        )
        uni = result.scalar_one_or_none()

        if uni is None:
            print("No row found named 'Federal University' — nothing changed.")
            return

        uni.official_name = "Federal University of Education, Zaria"
        print(f"Renamed 'Federal University' -> 'Federal University of Education, Zaria' (id={uni.id})")


if __name__ == "__main__":
    asyncio.run(rename())
