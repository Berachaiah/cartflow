"""
Final two corrections closing out the classification cleanup:
  - "Technical University" = First Technical University, Ibadan (State, Oyo)
  - "Pan-African University" = former name (pre-2013) of Pan-Atlantic
    University, Lagos (Private, Lagos) — renamed to avoid confusion
    with the African Union's own Pan-African University.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

CORRECTIONS = {
    "Technical University": ("state", "Oyo"),
    "Pan-African University": ("private", "Lagos"),
}


async def apply_corrections():
    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = {u.official_name: u for u in result.scalars().all()}

        applied = 0
        not_found = []

        for name, (itype, state) in CORRECTIONS.items():
            uni = unis.get(name)
            if uni is None:
                not_found.append(name)
                continue
            uni.institution_type = itype
            uni.state = state
            uni.status = "active"
            applied += 1

        print(f"Applied: {applied} / {len(CORRECTIONS)}")
        if not_found:
            print("Not found:")
            for name in not_found:
                print(f"  - {name}")

        # Final tally
        result = await session.execute(select(University))
        all_unis = result.scalars().all()
        remaining_null = sum(1 for u in all_unis if u.institution_type is None)
        print(f"\nTotal universities: {len(all_unis)}")
        print(f"Still NULL: {remaining_null}")


if __name__ == "__main__":
    asyncio.run(apply_corrections())
