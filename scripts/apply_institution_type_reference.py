"""
Applies a verified reference CSV (name, state, institution_type) against
the universities table. Only rows that match by normalized name are
updated — everything else is left as-is (NULL/unverified from the
earlier reset), so we never guess.

Expected CSV columns: University Name, State, Institution Type
Institution Type values: Federal | State | Private
"""

import sys
import csv
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "nigerian_universities_sample.csv"


def normalize(name: str) -> str:
    return " ".join(name.replace(",", "").split()).strip().lower()


async def apply_reference():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        reference = {
            normalize(row["University Name"]): {
                "state": row["State"].strip(),
                "institution_type": row["Institution Type"].strip().lower(),
            }
            for row in reader
        }

    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = result.scalars().all()

        matched = 0
        unmatched_in_db = []

        for uni in unis:
            key = normalize(uni.official_name)
            ref = reference.get(key)
            if ref:
                uni.institution_type = ref["institution_type"]
                uni.state = ref["state"]
                uni.status = "active"
                matched += 1
            else:
                unmatched_in_db.append(uni.official_name)

        print(f"Matched and updated: {matched} / {len(unis)}")
        print(f"Reference entries loaded: {len(reference)}")
        print(f"Still unmatched in DB (left as NULL/unverified): {len(unmatched_in_db)}")
        for name in unmatched_in_db:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(apply_reference())
