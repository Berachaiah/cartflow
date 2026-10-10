"""
Normalizes the `state` field for Abuja/FCT institutions to a single
consistent value: "FCT/Abuja". Catches known variants seen in the data
so far ("Federal Capital Territory", "FCT", "Abuja" alone).

Also sets Nile University's institution_type to Private (not yet in
the reference CSV).
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.models import University
from app.database.session import session_scope

FCT_VARIANTS = {"federal capital territory", "fct", "abuja"}


async def normalize():
    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = result.scalars().all()

        updated = 0
        for uni in unis:
            if uni.state and uni.state.strip().lower() in FCT_VARIANTS:
                if uni.state != "FCT/Abuja":
                    uni.state = "FCT/Abuja"
                    updated += 1

        # Nile University correction (not yet in the reference CSV)
        result = await session.execute(
            select(University).where(University.official_name == "Nile University")
        )
        nile = result.scalar_one_or_none()
        if nile is not None:
            nile.institution_type = "private"
            nile.state = "FCT/Abuja"
            nile.status = "active"
            print(f"Set institution_type=private, state=FCT/Abuja for 'Nile University' (id={nile.id})")
        else:
            print("No row found named 'Nile University'.")

        print(f"Normalized state -> 'FCT/Abuja' for {updated} row(s)")


if __name__ == "__main__":
    asyncio.run(normalize())
