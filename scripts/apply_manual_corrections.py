"""
Explicit, manually-verified corrections for rows the automated matchers
got wrong or couldn't resolve. Each entry here was individually checked
(NUC list + web verification for ownership changes like LAUTECH/KUST).
"official_name" must match exactly what's in the DB right now.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

CORRECTIONS = {
    # Confirmed private (typo/variant matches)
    "Lux Mundi University": ("private", "Abia"),
    "University of the Niger": ("private", "Anambra"),
    "Duke Medical University": ("private", "Cross River"),
    "West Midland Open University": ("private", "Oyo"),
    "Kevin Ezeh University": ("private", "Enugu"),
    "Tonnie Iredia University of Communication": ("private", "Edo"),
    "Cosmopolitan University": ("private", "FCT/Abuja"),
    "Gerar University of Medical Sciences": ("private", "Ogun"),
    "Elrazi University of Medical Sciences": ("private", "Kano"),
    "Shanahan University": ("private", "Anambra"),
    "Wesley Univ. of Science & Tech.": ("private", "Ondo"),
    "CETEP City University": ("private", "Lagos"),

    # Corrected — NOT private
    "Kano University of Science & Technology": ("state", "Kano"),
    "Niger Delta Unversity": ("state", "Bayelsa"),
    "University of Port-Harcourt": ("federal", "Rivers"),
    "Ladoke Akintola University of Technology": ("state", "Oyo"),
    "Michael Okpara Uni. of Agric.": ("federal", "Abia"),
    "Umaru Musa Yar'Adua University": ("state", "Katsina"),
    "Tai Solarin Univ. of Education": ("state", "Ogun"),
    "Usumanu Danfodiyo University": ("federal", "Sokoto"),
    "Nigeria Police Academy Wudil": ("federal", "Kano"),
    "Abubakar Tafawa Balewa University": ("federal", "Bauchi"),
    "Federal University, Ndufu-Alike": ("federal", "Ebonyi"),
    "Olabisi Onabanjo University Ago-Iwoye": ("state", "Ogun"),
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
            print(f"Not found in DB (name mismatch?): {len(not_found)}")
            for name in not_found:
                print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(apply_corrections())
