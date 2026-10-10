"""
Dumps the full universities table (name, state, institution_type) to a
CSV so we can eyeball it against the official NUC lists and catch stale
names (like the old "Kano University of Science & Technology" ->
"Aliko Dangote University of Science & Technology", or
"Nigerian-Turkish Nile University" -> "Nile University").
"""

import sys
import csv
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "universities_export.csv"


async def export():
    async with session_scope() as session:
        result = await session.execute(select(University).order_by(University.official_name))
        unis = result.scalars().all()

        with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["official_name", "state", "institution_type"])
            for u in unis:
                writer.writerow([u.official_name, u.state, u.institution_type])

        print(f"Exported {len(unis)} rows to {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(export())
