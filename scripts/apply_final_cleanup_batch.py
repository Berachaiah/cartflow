"""
One-off batch cleanup pass over the universities table:
  1. Typo fixes in official_name (Univeristy/Unversity -> University)
  2. Crescent University: fill blank state (Abeokuta, Ogun State)
  3. Expand abbreviated official_name entries to full form
  4. Rename "Pan-African University" -> "Pan-Atlantic University"
     (renamed in real life in 2013 to avoid confusion with the AU's own
     Pan-African University; short_name PAU is correct either way and
     institution_type=private / state=Lagos were already set previously)

Run from project root: python3 scripts/apply_final_cleanup_batch.py
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

# name -> new official_name
RENAMES = {
    "Gombe State Univeristy": "Gombe State University",
    "Niger Delta Unversity": "Niger Delta University",
    "Fountain Unveristy": "Fountain University",
    "Wesley Univ. of Science & Tech.": "Wesley University of Science and Technology",
    "Michael Okpara Uni. of Agric.": "Michael Okpara University of Agriculture, Umudike",
    "Tai Solarin Univ. of Education": "Tai Solarin University of Education",
    "Olusegun Agagu University of Sc. & Tech.": "Olusegun Agagu University of Science and Technology",
    "Pan-African University": "Pan-Atlantic University",
}

# name -> state (only filled if currently blank/None)
STATE_FIXES = {
    "Crescent University": "Ogun",
}


async def apply_batch():
    async with session_scope() as session:
        renamed, rename_not_found = 0, []
        for old_name, new_name in RENAMES.items():
            result = await session.execute(
                select(University).where(University.official_name == old_name)
            )
            uni = result.scalar_one_or_none()
            if uni is None:
                rename_not_found.append(old_name)
                continue
            uni.official_name = new_name
            renamed += 1

        state_filled, state_not_found, state_skipped = 0, [], []
        for name, state in STATE_FIXES.items():
            result = await session.execute(
                select(University).where(University.official_name == name)
            )
            uni = result.scalar_one_or_none()
            if uni is None:
                state_not_found.append(name)
                continue
            if uni.state:
                state_skipped.append(name)
                continue
            uni.state = state
            state_filled += 1

        print(f"Renamed: {renamed} / {len(RENAMES)}")
        if rename_not_found:
            print("  Not found:")
            for n in rename_not_found:
                print(f"    - {n}")

        print(f"State filled: {state_filled} / {len(STATE_FIXES)}")
        if state_skipped:
            print(f"  Skipped (already had a state): {state_skipped}")
        if state_not_found:
            print("  Not found:")
            for n in state_not_found:
                print(f"    - {n}")


if __name__ == "__main__":
    asyncio.run(apply_batch())
