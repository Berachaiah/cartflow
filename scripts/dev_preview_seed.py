"""
Dev-only preview seeder.

Builds a local **SQLite** database (`dev_preview.db`) with the organization
taxonomy + the full slice of real Nigerian universities exported from the
Supabase `organizations` table (`scripts/data/universities.json`), so the
Milestone-1 signup/directory pages can be exercised in a browser without the
(unreachable) Supabase Postgres. NOT used in production — prod runs the real
Alembic fold-in migration against Postgres.

The university list is NOT hardcoded here: it's loaded from the JSON export so
a re-seed always matches the cleaned production data (add rows there, re-seed,
done). Each record's own `id`/`slug`/`status` are preserved verbatim.

Idempotent: drops and recreates the file each run.

Run:
    DATABASE_URL="sqlite+aiosqlite:///./dev_preview.db" \
        ./venv/bin/python scripts/dev_preview_seed.py
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev_preview.db")

from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.models.organization import (  # noqa: E402
    Organization,
    OrganizationGroup,
    OrganizationType,
)

# Stable taxonomy ids — must match the values other dev tooling/tests expect.
EDU_GROUP_ID = uuid.UUID("11111111-0000-4000-8000-000000000001")
UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")

# The cleaned export of the production `organizations` table. Bundled in the
# repo so the preview DB mirrors real data (Veritas, all 100 universities, …).
UNIVERSITIES_JSON = Path(__file__).resolve().parent / "data" / "universities.json"


def _load_universities() -> list[dict]:
    """Read the export, tolerating the two shapes `source_metadata` arrives in.

    In the Supabase JSON export each row's `source_metadata` is a JSON *string*
    (double-encoded), while the model column is JSON. Decode it to a dict so the
    seeded row round-trips as real JSON rather than a quoted string. `aliases`
    is passed through as-is (currently null for every row)."""
    rows = json.loads(UNIVERSITIES_JSON.read_text())
    for row in rows:
        meta = row.get("source_metadata")
        if isinstance(meta, str):
            try:
                row["source_metadata"] = json.loads(meta)
            except (ValueError, TypeError):
                row["source_metadata"] = {"raw": meta}
    return rows


async def main() -> None:
    universities = _load_universities()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(OrganizationGroup(id=EDU_GROUP_ID, name="Education", slug="education", sort_order=1))
        await s.flush()
        s.add(
            OrganizationType(
                id=UNIVERSITY_TYPE_ID,
                organization_group_id=EDU_GROUP_ID,
                name="University",
                slug="university",
                sort_order=1,
            )
        )
        await s.flush()

        for row in universities:
            s.add(
                Organization(
                    # Preserve the exported primary key so the preview DB lines
                    # up 1:1 with production ids.
                    id=uuid.UUID(row["id"]),
                    organization_type_id=UNIVERSITY_TYPE_ID,
                    official_name=row["official_name"],
                    short_name=row.get("short_name"),
                    slug=row["slug"],
                    country=row.get("country") or "Nigeria",
                    state=row.get("state"),
                    institution_type=row.get("institution_type"),
                    aliases=row.get("aliases"),
                    source_metadata=row.get("source_metadata"),
                    status=row.get("status") or "active",
                )
            )
        await s.commit()

    print(f"Seeded {len(universities)} universities into {os.environ['DATABASE_URL']}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
