"""
Applies the fuller reference CSV (from favourdev1/Nigerian-University-Api's
seeder, 141 rows: Federal/State/Private) against the universities table.

Matching strategy, in order:
  1. Exact normalized full-name match
  2. Normalized match on the name before the first comma
     (handles "University of Lagos, Lagos" -> "University of Lagos")

Only rows currently NULL are touched — anything already confirmed
'state' from the earlier reset is left alone, so this can never
downgrade a confirmed value.
"""

import sys
import csv
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "nigerian_universities_reference.csv"


def normalize(name: str) -> str:
    return " ".join(name.replace(",", "").split()).strip().lower()


def before_comma(name: str) -> str:
    return name.split(",")[0].strip()


async def apply_reference():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    full_lookup = {}
    prefix_lookup = {}
    for row in rows:
        name = row["University Name"]
        entry = {
            "state": row["State"].strip(),
            "institution_type": row["Institution Type"].strip().lower(),
        }
        full_lookup[normalize(name)] = entry
        prefix_lookup[normalize(before_comma(name))] = entry

    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = result.scalars().all()

        updated = 0
        still_null = []

        for uni in unis:
            if uni.institution_type is not None:
                continue  # already confirmed — never touch

            key = normalize(uni.official_name)
            ref = full_lookup.get(key) or prefix_lookup.get(key)

            if ref:
                uni.institution_type = ref["institution_type"]
                uni.state = ref["state"]
                uni.status = "active"
                updated += 1
            else:
                still_null.append(uni.official_name)

        print(f"Matched and updated: {updated}")
        print(f"Reference rows loaded: {len(rows)}")
        print(f"Still NULL: {len(still_null)}")
        for name in still_null:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(apply_reference())
