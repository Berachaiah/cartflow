"""
Best-effort second pass for short_name — only well-known, confidently
verifiable abbreviations. Leaves obscure/newer private universities
blank rather than guess.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

SHORT_NAMES = {
    "Rivers State University": "RSU",
    "Joseph Sarwuan Tarka University": "JOSTUM",
    "Umaru Musa Yar'Adua University": "UMYU",
    "Usumanu Danfodiyo University": "UDUS",
    "Nigeria Police Academy Wudil": "POLAC",
    "Abubakar Tafawa Balewa University": "ATBU",
    "Niger Delta Unversity": "NDU",
    "University of Port-Harcourt": "UNIPORT",
    "African University of Science & Technology": "AUST",
    "Jigawa State University": "JSU",
    "Aliko Dangote University of Science & Technology": "ADUSTECH",
    "Nile University": "NUN",
    "Tai Solarin Univ. of Education": "TASUED",
    "Michael Okpara Uni. of Agric.": "MOUAU",
    "University of Cross River State": "UNICROSS",
    "Gombe State Univeristy": "GSU",
    "Ladoke Akintola University of Technology": "LAUTECH",
    "Technical University": "TECH-U",
    "Redeemer's University": "RUN",
    "Godfrey Okoye University": "GOUNI",
    "Federal University of Education, Zaria": "FUEZ",
    "Alex Ekwueme University, Ndufu-Alike": "AE-FUNAI",
    "Pan-African University": "PAU",
}


async def apply_short_names():
    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = {u.official_name: u for u in result.scalars().all()}

        applied = 0
        skipped_has_value = 0
        not_found = []

        for name, abbr in SHORT_NAMES.items():
            uni = unis.get(name)
            if uni is None:
                not_found.append(name)
                continue
            if uni.short_name:
                skipped_has_value += 1
                continue
            uni.short_name = abbr
            applied += 1

        print(f"Applied: {applied}")
        if skipped_has_value:
            print(f"Already had a value (skipped): {skipped_has_value}")
        if not_found:
            print("Not found:")
            for n in not_found:
                print(f"  - {n}")

        # Final tally
        result = await session.execute(select(University))
        all_unis = result.scalars().all()
        still_missing = sum(1 for u in all_unis if not u.short_name)
        print(f"\nTotal universities: {len(all_unis)}")
        print(f"Still missing short_name: {still_missing}")


if __name__ == "__main__":
    asyncio.run(apply_short_names())
