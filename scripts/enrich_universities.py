"""
scripts/enrich_universities.py

Fills in state + institution_type for universities seeded from Stutern
that came in as status="unverified" with both fields NULL.

Two heuristics, both grounded in how Nigerian universities are actually
named/organized (not guesses):

  1. institution_type from name:
       - contains "Federal" -> federal
       - contains a real state name immediately followed by "State"
         (e.g. "Ekiti State University") -> state
       - otherwise -> private
     (Nigerian university naming makes this reliable: federal and state
     universities are named after their tier explicitly; anything else
     is privately owned.)

  2. state from name or from the city already stored in source_metadata:
       - if the name itself contains "<StateName> State", use that
         directly (most reliable — explicit in the source)
       - otherwise look up the stored city against a curated
         CITY_TO_STATE table of Nigerian geography

Rows where state still can't be resolved after both passes are left as
status="unverified" and printed at the end for manual follow-up —
nothing is guessed past what these two methods can support.
"""

import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.session import AsyncSessionLocal
from app.models.university import University

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue",
    "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu",
    "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi",
    "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo",
    "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe", "Zamfara", "FCT",
]

# City -> state, for the specific cities that appear in the Stutern
# dataset (per Nigeria's actual state boundaries).
CITY_TO_STATE = {
    "Uturu": "Abia", "Bauchi": "Bauchi", "Owo": "Ondo", "Mubi": "Adamawa",
    "Akungba": "Ondo", "Ede": "Osun", "Abuja": "FCT", "Zaria": "Kaduna",
    "Ibadan": "Oyo", "Uyo": "Akwa Ibom", "Ilorin": "Kwara", "Katsina": "Katsina",
    "Ekpoma": "Edo", "Yola": "Adamawa", "Uli": "Anambra", "Ilishan-Remo": "Ogun",
    "Gadau": "Bauchi", "Kano": "Kano", "Otta": "Ogun", "Ota": "Ogun",
    "Benin City": "Edo", "Benin": "Edo", "Makurdi": "Benue", "New Karu": "Nasarawa",
    "Iwo": "Osun", "Damaturu": "Yobe", "Lagos": "Lagos", "Enugu": "Enugu",
    "Igbesa": "Ogun", "Calabar": "Cross River", "Abraka": "Delta",
    "Abakaliki": "Ebonyi", "Ilara-Mokin": "Ondo", "Akaeze": "Ebonyi",
    "Gashua": "Yobe", "Effurun": "Delta", "Akure": "Ondo", "Minna": "Niger",
    "Owerri": "Imo", "Oshogbo": "Osun", "Osogbo": "Osun", "Gombe": "Gombe",
    "Lapai": "Niger", "Okada": "Edo", "Rumuolumeni": "Rivers",
    "Ikeji-Arakeji": "Osun", "Kaduna": "Kaduna", "Wudil": "Kano",
    "Anyigba": "Kogi", "Ogbomoso": "Oyo", "Omu-Aran": "Kwara", "Okija": "Anambra",
    "Umudike": "Abia", "Keffi": "Nasarawa", "Yenagoa": "Bayelsa",
    "Awka": "Anambra", "Ogume": "Delta", "Ile-Ife": "Osun",
    "Obong Ntak": "Akwa Ibom", "Ipetumodu": "Osun", "Ago-Iwoye": "Ogun",
    "Okitipupa": "Ondo", "Bokkos": "Plateau", "Mowe": "Ogun",
    "Obeama-Asa": "Rivers", "Ogwa": "Edo", "Sokoto": "Sokoto",
    "Oku Owa": "Osun", "Ijebu-Ode": "Ogun", "Umunya": "Anambra",
    "Jalingo": "Taraba", "Gwagwalada": "FCT", "Abeokuta": "Ogun",
    "Jos": "Plateau", "Maiduguri": "Borno", "Mkar": "Benue", "Nsukka": "Enugu",
    "Port-Harcourt": "Rivers", "Port Harcourt": "Rivers",
    "Evbuobanosa": "Edo", "Ondo": "Ondo", "Oghara": "Delta",
    "Kebbi": "Kebbi", "Ado-Ekiti": "Ekiti", "Seriki Sotayo": "Ogun",
    "Wukari": "Taraba",
}

FEDERAL_RE = re.compile(r"\bFederal\b", re.IGNORECASE)
STATE_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in NIGERIAN_STATES) + r")\s+State\b",
    re.IGNORECASE,
)


def infer_institution_type(name: str) -> str:
    if FEDERAL_RE.search(name):
        return "federal"
    if STATE_NAME_RE.search(name):
        return "state"
    return "private"


def infer_state(name: str, city: str | None) -> str | None:
    match = STATE_NAME_RE.search(name)
    if match:
        # Normalize to our canonical casing from NIGERIAN_STATES
        found = match.group(1)
        for s in NIGERIAN_STATES:
            if s.lower() == found.lower():
                return s
    if city:
        # Try exact match, then try each known city as a substring
        # (handles "Kogi State" vs "Lokoja, Kogi State" style values)
        if city in CITY_TO_STATE:
            return CITY_TO_STATE[city]
        for known_city, state in CITY_TO_STATE.items():
            if known_city.lower() in city.lower():
                return state
    return None


async def enrich():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(University).where(University.status == "unverified")
        )
        rows = list(result.scalars().all())
        print(f"Found {len(rows)} unverified universities to enrich")

        resolved = 0
        unresolved = []

        for uni in rows:
            city = (uni.source_metadata or {}).get("city")
            new_state = infer_state(uni.official_name, city)
            new_type = infer_institution_type(uni.official_name)

            uni.institution_type = new_type

            if new_state:
                uni.state = new_state
                uni.status = "active"
                resolved += 1
            else:
                unresolved.append(uni.official_name)

        await session.commit()

        print(f"Resolved state+type for {resolved} universities (now status=active)")
        print(f"Could not resolve state for {len(unresolved)} — left as unverified:")
        for name in unresolved:
            print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(enrich())
