"""
Applies the official NUC Federal + State universities list against the
universities table. Only rows currently NULL are touched — anything
already confirmed is left alone. Only overwrites `state` when the
reference row actually has one (older federal unis often don't list
a state in their NUC entry, e.g. "University of Ibadan").
"""

import sys
import csv
import asyncio
import difflib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "nuc_federal_state_universities.csv"

ABBREVIATIONS = {
    " univ. ": " university ",
    " univ ": " university ",
    " uni. ": " university ",
    "unveristy": "university",
    "univeristy": "university",
    " tech. ": " technology ",
    " sci. ": " science ",
    " & ": " and ",
    " educ. ": " education ",
}


def normalize(name: str) -> str:
    n = " " + name.lower().replace(",", " ").strip() + " "
    n = " ".join(n.split())
    n = " " + n + " "
    for k, v in ABBREVIATIONS.items():
        n = n.replace(k, v)
    return " ".join(n.split())


async def apply_reference():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    exact_lookup = {}
    for row in rows:
        entry = {"state": row["State"].strip(), "institution_type": row["Institution Type"].strip().lower()}
        exact_lookup[normalize(row["University Name"])] = entry
        full = row.get("Full Name (as listed)", "")
        if full:
            exact_lookup[normalize(full.split(",")[0])] = entry

    reference_names = list(exact_lookup.keys())

    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = result.scalars().all()

        updated = 0
        fuzzy_suggestions = []
        no_match = []

        for uni in unis:
            if uni.institution_type is not None:
                continue

            key = normalize(uni.official_name)
            ref = exact_lookup.get(key)

            if ref:
                uni.institution_type = ref["institution_type"]
                if ref["state"]:
                    uni.state = ref["state"]
                uni.status = "active"
                updated += 1
                continue

            close = difflib.get_close_matches(key, reference_names, n=1, cutoff=0.75)
            if close:
                fuzzy_suggestions.append((uni.official_name, close[0]))
            else:
                no_match.append(uni.official_name)

        print(f"Exact matched and updated: {updated}")
        print(f"\nFuzzy suggestions (NOT applied): {len(fuzzy_suggestions)}")
        for db_name, suggestion in fuzzy_suggestions:
            print(f"  DB: {db_name!r}  ~=  Reference: {suggestion!r}")
        print(f"\nNo match at all: {len(no_match)}")
        for name in no_match:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(apply_reference())
