"""
One-off rename: "Nigerian-Turkish Nile University" is now commonly
known as just "Nile University" (Abuja). Updates official_name in place.
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
            select(University).where(University.official_name == "Nigerian-Turkish Nile University")
        )
        uni = result.scalar_one_or_none()

        if uni is None:
            print("No row found with that exact name — nothing changed.")
            return

        uni.official_name = "Nile University"
        print(f"Renamed: 'Nigerian-Turkish Nile University' -> 'Nile University' (id={uni.id})")


if __name__ == "__main__":
    asyncio.run(rename())
