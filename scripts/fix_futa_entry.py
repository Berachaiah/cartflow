"""
One-off correction: the "Federal Uni of Technology, Akure" row was created
via the resolve() get-or-create endpoint during testing, landing as
status="unverified" with no state/institution_type. FUTA is a real,
well-known federal university in Akure, Ondo State — correcting it here
rather than leaving it to be caught by a future review pass.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope


async def fix():
    async with session_scope() as session:
        result = await session.execute(
            select(University).where(University.official_name == "Federal Uni of Technology, Akure")
        )
        uni = result.scalar_one_or_none()

        if uni is None:
            print("No row found named 'Federal Uni of Technology, Akure' — nothing changed.")
            return

        uni.official_name = "Federal University of Technology, Akure"
        uni.short_name = "FUTA"
        uni.state = "Ondo"
        uni.institution_type = "federal"
        uni.status = "active"
        print(f"Fixed FUTA entry (id={uni.id}): now active, federal, Ondo, short_name=FUTA")


if __name__ == "__main__":
    asyncio.run(fix())
