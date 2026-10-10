"""
University repository: typeahead search + get-or-create resolution.

Design notes:
  - search() does a simple ILIKE prefix/contains match on official_name,
    short_name, and aliases — good enough for a signup typeahead without
    needing full-text search infra yet.
  - get_or_create() is the important one: when a user types a name we
    don't have, we don't want silent duplicates ("University of Lagos"
    vs "Univ of Lagos" as two separate rows). We first try an exact
    normalized match (against both official_name and short_name), then
    a fuzzy match (difflib) against all existing names/short_names
    before deciding it's genuinely new.

  - Divergent-suffix guard: names like "Federal University of Technology,
    Akure" (FUTA, Ondo) and "Federal University of Technology, Owerri"
    (FUTO, Imo) share a very long common institutional prefix but refer
    to two entirely different, real universities — the distinguishing
    part is the trailing campus/city name. A plain similarity ratio over
    the whole string scores these as near-identical and would silently
    merge them. To guard against that, any fuzzy candidate is rejected
    unless the last significant token (the part after the final comma,
    or the last word if there's no comma) also matches closely — not
    just the string as a whole.

  New rows are inserted with state/institution_type left NULL and
  status="unverified" so they surface in the same review/export workflow
  used for the seed data.
"""

import difflib
import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.university import University
from app.repositories.base import BaseRepository

FUZZY_CUTOFF = 0.82
TAIL_CUTOFF = 0.75  # stricter check on the distinguishing suffix (campus/city)

# Common abbreviation patterns seen in real-world university name entry
# (same expansions used in the one-off data-cleanup scripts).
_ABBREVIATION_EXPANSIONS = [
    (r"\buniv\b\.?", "university"),
    (r"\buni\b\.?", "university"),
    (r"\bsc\b\.?", "science"),
    (r"\btech\b\.?", "technology"),
    (r"\b&\b", "and"),
]


def _normalize(name: str) -> str:
    key = name.lower()
    for pattern, replacement in _ABBREVIATION_EXPANSIONS:
        key = re.sub(pattern, replacement, key)
    return re.sub(r"[^a-z0-9]+", " ", key).strip()


def _tail(normalized_name: str) -> str:
    """The distinguishing part of a name — everything after the last comma
    in the original casing gets normalized too, but since we only have the
    normalized string here, fall back to the last 1-2 words as a proxy for
    'campus/city' when there's no comma to split on."""
    words = normalized_name.split()
    return " ".join(words[-2:]) if len(words) >= 2 else normalized_name


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


class UniversityRepository(BaseRepository[University]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, University)

    async def search(self, query: str, limit: int = 10) -> list[University]:
        """Typeahead search for signup. Empty/short queries return nothing —
        don't dump the whole table into a dropdown."""
        query = query.strip()
        if len(query) < 2:
            return []

        pattern = f"%{query}%"
        stmt = (
            select(University)
            .where(
                University.deleted_at.is_(None),
                University.status == "active",
                or_(
                    University.official_name.ilike(pattern),
                    University.short_name.ilike(pattern),
                ),
            )
            .order_by(University.official_name)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_or_create(self, raw_name: str) -> tuple[University, bool]:
        """Returns (university, created). `created=True` means this was a
        brand-new, unverified row — surface that to the frontend/signup
        flow so the user knows it'll be reviewed."""
        if raw_name is None:
            raise ValueError("University name cannot be None")
        raw_name = raw_name.strip()
        if not raw_name:
            raise ValueError("University name cannot be empty")

        target_key = _normalize(raw_name)
        target_tail = _tail(target_key)

        result = await self.db.execute(
            select(University).where(University.deleted_at.is_(None))
        )
        existing = list(result.scalars().all())

        # Build lookup keys from both official_name and short_name
        by_key: dict[str, University] = {}
        for u in existing:
            by_key[_normalize(u.official_name)] = u
            if u.short_name:
                by_key[_normalize(u.short_name)] = u

        # 1. Exact normalized match (official_name or short_name)
        if target_key in by_key:
            return by_key[target_key], False

        # 2. Fuzzy match, guarded against divergent-suffix false merges
        candidates = difflib.get_close_matches(
            target_key, list(by_key.keys()), n=3, cutoff=FUZZY_CUTOFF
        )
        for candidate_key in candidates:
            candidate_tail = _tail(candidate_key)
            if _similar(target_tail, candidate_tail) >= TAIL_CUTOFF:
                return by_key[candidate_key], False
            # else: whole-string looked similar, but the distinguishing
            # tail (campus/city) diverges too much — treat as a different
            # institution, keep checking other candidates.

        # 3. Nothing close enough (or all candidates failed the tail
        # check) — create a new, unverified row.
        new_uni = University(
            official_name=raw_name,
            slug=self._slugify(raw_name),
            state=None,
            institution_type=None,
            status="unverified",
            source_metadata={"source": "user_submitted"},
        )
        self.db.add(new_uni)
        await self.db.flush()
        return new_uni, True

    @staticmethod
    def _slugify(name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return f"{base}-{uuid.uuid4().hex[:6]}"
