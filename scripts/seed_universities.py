"""
scripts/seed_universities.py

Seeds AND enriches the `universities` table from two sources:

  1. Stutern/world-universities nigerian-universities.csv — baseline list
     of ~129 older institutions. Only gives "Name, City" — no state or
     institution_type — so these rows land as status="unverified".

  2. NUC_REFERENCE_DATA — a curated list compiled from NUC's own site
     (nuc.edu.ng) and cross-checked against Punch/PM News/Arise News.
     Currently covers the 2023 batch (37 private universities) and 2025
     batch (11 private universities). This list does double duty:
       - INSERT: if the slug doesn't exist yet, add it as a new,
         verified ("active") row.
       - UPDATE: if the slug already exists (e.g. it came in via Stutern
         as "unverified"), fill in/correct state + institution_type and
         flip status to "active" — NUC data always wins over Stutern's
         when both describe the same institution.

Growing NUC_REFERENCE_DATA over time (adding established institutions'
correct state/type, not just new ones) is how Stutern's "unverified"
backlog gets cleaned up — the upsert logic already supports this, no
script changes needed, just more entries.

Dedup key: slugify(name), matching the model's unique `slug` column.
Safe to re-run any number of times.
"""

import asyncio
import re
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import AsyncSessionLocal
from app.models.university import University

STUTERN_CSV_URL = "https://raw.githubusercontent.com/Stutern/world-universities/master/nigerian-universities.csv"

# institution_type + state verified against NUC/news reporting.
# Extend this list over time with established institutions too — any
# entry here whose slug matches an existing (Stutern-sourced) row will
# UPDATE that row's state/institution_type/status rather than skip it.
NUC_REFERENCE_DATA: list[tuple[str, str, str]] = [
    # (name, state, institution_type)
    # 2023 batch — 37 private universities licensed Jan 1 - Jun 27, 2023
    ("Lux Mundi University", "Abia", "private"),
    ("Maduka University", "Enugu", "private"),
    ("Peaceland University", "Enugu", "private"),
    ("Amadeus University", "Abia", "private"),
    ("Vision University", "Ogun", "private"),
    ("Azman University", "Kano", "private"),
    ("Huda University", "Zamfara", "private"),
    ("Franco British International University", "Kaduna", "private"),
    ("Canadian University of Nigeria", "FCT", "private"),
    ("Miva Open University", "FCT", "private"),
    ("Gerar University of Medical Sciences", "Ogun", "private"),
    ("British Canadian University", "Cross River", "private"),
    ("Hensard University", "Bayelsa", "private"),
    ("Phoenix University", "Nasarawa", "private"),
    ("Wigwe University", "Rivers", "private"),
    ("Hillside University of Science and Technology", "Ekiti", "private"),
    ("University of the Niger", "Anambra", "private"),
    ("Elrazi University of Medical Sciences", "Kano", "private"),
    ("Venite University", "Ekiti", "private"),
    ("Shanahan University", "Anambra", "private"),
    ("Duke Medical University", "Cross River", "private"),
    ("Mercy Medical University", "Ondo", "private"),
    ("Cosmopolitan University", "FCT", "private"),
    ("Iconic Open University", "Sokoto", "private"),
    ("West Midland Open University", "Oyo", "private"),
    # 2025 batch — 11 private universities licensed 30 April 2025
    ("New City University", "Ogun", "private"),
    ("Lens University", "Kwara", "private"),
    ("Kevin Ezeh University", "Enugu", "private"),
    ("Southern Atlantic University", "Akwa Ibom", "private"),
    ("University of Fortune", "Ondo", "private"),
    ("Minaret University", "Osun", "private"),
    ("Abdulrasaq Abubakar Toyin University", "Kwara", "private"),
    ("Monarch University", "Ogun", "private"),
    ("Tonnie Iredia University of Communication", "Edo", "private"),
    ("Isaac Balami University of Aeronautics and Management", "Lagos", "private"),
    ("Eranova University", "FCT", "private"),
]


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def parse_stutern_line(line: str) -> tuple[str, str | None]:
    """Split on the LAST comma — a few names contain a comma themselves."""
    line = line.strip().rstrip(".")
    if "," in line:
        name, _, city = line.rpartition(",")
        return name.strip(), city.strip() or None
    return line, None


async def fetch_stutern_names() -> list[tuple[str, str | None]]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(STUTERN_CSV_URL)
        resp.raise_for_status()
    lines = [l for l in resp.text.splitlines() if l.strip()]
    return [parse_stutern_line(l) for l in lines]


async def seed():
    stutern = await fetch_stutern_names()
    print(f"Fetched {len(stutern)} entries from Stutern CSV")
    print(f"Have {len(NUC_REFERENCE_DATA)} NUC reference entries")

    async with AsyncSessionLocal() as session:
        # slug -> University instance, for all rows currently in the DB
        existing_by_slug: dict[str, University] = {
            u.slug: u
            for u in (await session.execute(select(University))).scalars().all()
        }
        print(f"{len(existing_by_slug)} universities already in DB")

        inserted = 0
        skipped = 0

        # Pass 1: Stutern — insert only, never overwrites an existing row
        for name, city in stutern:
            slug = slugify(name)
            if not slug or slug in existing_by_slug:
                skipped += 1
                continue
            uni = University(
                official_name=name,
                slug=slug,
                state=None,
                institution_type=None,
                status="unverified",
                source_metadata={"source": "stutern/world-universities", "city": city},
            )
            session.add(uni)
            existing_by_slug[slug] = uni
            inserted += 1

        await session.flush()  # so pass 2 can see pass 1's new rows by slug

        # Pass 2: NUC reference data — INSERT if new, UPDATE if it already
        # exists (NUC data always overrides Stutern's placeholder values)
        updated = 0
        for name, state, institution_type in NUC_REFERENCE_DATA:
            slug = slugify(name)
            if not slug:
                continue

            if slug in existing_by_slug:
                uni = existing_by_slug[slug]
                if uni.state != state or uni.institution_type != institution_type or uni.status != "active":
                    uni.state = state
                    uni.institution_type = institution_type
                    uni.status = "active"
                    uni.source_metadata = {
                        **(uni.source_metadata or {}),
                        "enriched_by": "nuc_provisional_license_reports_2023_2025",
                    }
                    updated += 1
            else:
                uni = University(
                    official_name=name,
                    slug=slug,
                    state=state,
                    institution_type=institution_type,
                    status="active",
                    source_metadata={"source": "nuc_provisional_license_reports_2023_2025"},
                )
                session.add(uni)
                existing_by_slug[slug] = uni
                inserted += 1

        await session.commit()

    print(f"Inserted {inserted} new, updated {updated} existing, skipped {skipped} unchanged duplicates")


if __name__ == "__main__":
    asyncio.run(seed())
