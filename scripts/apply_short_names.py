"""
Fills in `short_name` (abbreviation) from the seeder reference data.
Only touches rows where short_name is currently NULL/empty. Matches
by normalized full name, then by name before the first comma (to
handle "University of Lagos, Lagos" -> "University of Lagos").
"""

import sys
import csv
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "nigerian_universities_short_names.csv"


def normalize(name: str) -> str:
    return " ".join(name.replace(",", "").split()).strip().lower()


def before_comma(name: str) -> str:
    return name.split(",")[0].strip()


async def apply_short_names():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    full_lookup = {}
    prefix_lookup = {}
    for row in rows:
        name = row["University Name"]
        abbr = row["Short Name"].strip()
        full_lookup[normalize(name)] = abbr
        prefix_lookup[normalize(before_comma(name))] = abbr

    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = result.scalars().all()

        updated = 0
        still_missing = []

        for uni in unis:
            if uni.short_name:
                continue  # already has one — don't overwrite

            key = normalize(uni.official_name)
            abbr = full_lookup.get(key) or prefix_lookup.get(key)

            if abbr:
                uni.short_name = abbr
                updated += 1
            else:
                still_missing.append(uni.official_name)

        print(f"Filled short_name for: {updated}")
        print(f"Still missing: {len(still_missing)}")
        for name in still_missing:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(apply_short_names())
