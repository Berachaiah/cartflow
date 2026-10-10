"""
Batch of verified corrections found by cross-checking the DB against
the current NUC federal/state/private lists:
  - Renames: institution_type/state were already correct, just the
    name is outdated (post-rename NUC entries).
  - Reclassification: Bukar Abba Ibrahim University was wrongly
    marked 'federal' — it's a Yobe State-owned university (formerly
    Yobe State University).
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

# old_name -> new_name (pure renames — type/state untouched)
RENAMES = {
    "Kano University of Science & Technology": "Aliko Dangote University of Science & Technology",
    "Benue State University": "Rev. Fr. Moses Orshio Adasu University",
    "Kogi State University Anyigba": "Prince Abubakar Audu University",
    "Cross River State University of Science &Technology": "University of Cross River State",
    "Federal University, Ndufu-Alike": "Alex Ekwueme University, Ndufu-Alike",
    "Rivers State University of Science & Technology": "Rivers State University",
    "University of Agriculture": "Joseph Sarwuan Tarka University",
    "Ondo State University of Science & Technology": "Olusegun Agagu University of Sc. & Tech.",
    "Akwa Ibom State University of Technology": "Akwa Ibom State University",
    "University of Nigeria": "University of Nigeria, Nsukka",
    "Federal University of Technology": "Federal University of Technology, Owerri",
    "Federal University of Petroleum Resources": "Federal University of Petroleum Resources, Effurun",
    "Kebbi State University": "Kebbi State University of Science and Technology, Aliero",
}

# name -> (institution_type, state) — genuine reclassification, not just a rename
RECLASSIFICATIONS = {
    "Bukar Abba Ibrahim University": ("state", "Yobe"),
}


async def apply_all():
    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = {u.official_name: u for u in result.scalars().all()}

        renamed = 0
        not_found_rename = []
        for old_name, new_name in RENAMES.items():
            uni = unis.get(old_name)
            if uni is None:
                not_found_rename.append(old_name)
                continue
            uni.official_name = new_name
            renamed += 1

        reclassified = 0
        not_found_reclass = []
        for name, (itype, state) in RECLASSIFICATIONS.items():
            uni = unis.get(name)
            if uni is None:
                not_found_reclass.append(name)
                continue
            uni.institution_type = itype
            uni.state = state
            reclassified += 1

        print(f"Renamed: {renamed} / {len(RENAMES)}")
        if not_found_rename:
            print("  Not found:")
            for n in not_found_rename:
                print(f"    - {n}")

        print(f"Reclassified: {reclassified} / {len(RECLASSIFICATIONS)}")
        if not_found_reclass:
            print("  Not found:")
            for n in not_found_reclass:
                print(f"    - {n}")


if __name__ == "__main__":
    asyncio.run(apply_all())
