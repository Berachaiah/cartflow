"""
One-off correction: the earlier enrichment script only reliably detected
'state' universities (name contains 'State'). Federal universities were
being defaulted to 'private', which is wrong. This resets institution_type
to NULL for every row that isn't 'state', so the field only holds values
we're actually confident about. Re-classification (federal vs private)
can be done properly afterward against an authoritative NUC list.
"""

import sys
import asyncio
from pathlib import Path

# scripts/ is one level below the project root — add the root to sys.path
# so `app.*` imports resolve regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update

from app.models import University
from app.database.session import session_scope


async def reset():
    async with session_scope() as session:
        result = await session.execute(select(University))
        unis = result.scalars().all()

        total = len(unis)
        kept_state = sum(1 for u in unis if u.institution_type == "state")
        to_null = total - kept_state

        await session.execute(
            update(University)
            .where(University.institution_type != "state")
            .values(institution_type=None, status="unverified")
        )

        print(f"Total universities: {total}")
        print(f"Kept as 'state': {kept_state}")
        print(f"Reset to NULL (institution_type + status=unverified): {to_null}")


if __name__ == "__main__":
    asyncio.run(reset())
