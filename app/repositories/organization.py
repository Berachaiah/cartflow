"""
Organization repositories: typeahead search, fuzzy get-or-create resolution,
directory listing, and the request/deferred-signup tables.

The matching logic (`_normalize`, `_tail`, `_similar`, the exact-then-fuzzy
resolution with the divergent-suffix guard) is PORTED VERBATIM from
`app/repositories/university.py` — it is subtle and correct, so it is reused,
not rewritten. See that module's docstring for the FUTA-vs-FUTO rationale.

Two deliberate changes from the university version:
  - Queries are scoped by `organization_type_id` (V1 passes the University
    type) so a university name is never fuzzy-matched against, say, a business.
  - `search()` / `list_directory()` do NOT filter on `status == "active"`.
    In the seed data only ~48 of ~160 universities are "active" (NUC-curated);
    the rest are real institutions from a published CSV, merely "unverified"
    (state/type not yet cross-checked). Filtering them out would hide most
    universities from the signup typeahead and directory. Visibility is gated
    on `deleted_at IS NULL` only. (New user-submitted orgs are created only via
    admin-approved requests, so this is not a spam vector.)
"""

import difflib
import re
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, OrganizationGroup, OrganizationType
from app.models.organization_request import OrganizationRequest, SignupRequest
from app.repositories.base import BaseRepository

FUZZY_CUTOFF = 0.82
TAIL_CUTOFF = 0.75  # stricter check on the distinguishing suffix (campus/city)

# Common abbreviation patterns seen in real-world institution name entry.
_ABBREVIATION_EXPANSIONS = [
    (r"\buniv\b\.?", "university"),
    (r"\buni\b\.?", "university"),
    (r"\bsc\b\.?", "science"),
    (r"\btech\b\.?", "technology"),
    # `&` is a non-word char, so `\b&\b` never fires; match it with any
    # surrounding whitespace and normalize to a spaced "and".
    (r"\s*&\s*", " and "),
]


def _normalize(name: str) -> str:
    key = name.lower()
    for pattern, replacement in _ABBREVIATION_EXPANSIONS:
        key = re.sub(pattern, replacement, key)
    return re.sub(r"[^a-z0-9]+", " ", key).strip()


def _tail(normalized_name: str) -> str:
    """The distinguishing part of a name (campus/city). With only the
    normalized string available, use the last 1-2 words as a proxy."""
    words = normalized_name.split()
    return " ".join(words[-2:]) if len(words) >= 2 else normalized_name


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{base}-{uuid.uuid4().hex[:6]}"


class OrganizationRepository(BaseRepository[Organization]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Organization)

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.db.execute(
            select(Organization).where(
                Organization.slug == slug, Organization.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _group_type_subquery(group_id: uuid.UUID):
        """Type ids belonging to a group, as a scalar subquery. Lets callers
        scope a query to a whole group (e.g. all Education types: university,
        polytechnic, college, …) without the caller pre-fetching the id list."""
        return select(OrganizationType.id).where(
            OrganizationType.organization_group_id == group_id
        )

    async def search(
        self,
        query: str,
        *,
        type_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
        limit: int = 10,
    ) -> list[Organization]:
        """Typeahead search for signup. Empty/short queries return nothing —
        don't dump the whole table into a dropdown. Scope with `type_id` (one
        type) or `group_id` (any type in the group); if both are given, both
        apply."""
        query = query.strip()
        if len(query) < 2:
            return []

        pattern = f"%{query}%"
        conditions = [
            Organization.deleted_at.is_(None),
            or_(
                Organization.official_name.ilike(pattern),
                Organization.short_name.ilike(pattern),
            ),
        ]
        if type_id is not None:
            conditions.append(Organization.organization_type_id == type_id)
        if group_id is not None:
            conditions.append(
                Organization.organization_type_id.in_(self._group_type_subquery(group_id))
            )

        stmt = (
            select(Organization)
            .where(*conditions)
            .order_by(Organization.official_name)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_directory(
        self,
        *,
        country: str | None = None,
        state: str | None = None,
        type_id: uuid.UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Organization], int]:
        """Paginated directory (spec item #4). Returns (rows, total_count)."""
        conditions = [Organization.deleted_at.is_(None)]
        if type_id is not None:
            conditions.append(Organization.organization_type_id == type_id)
        if country:
            conditions.append(Organization.country == country)
        if state:
            conditions.append(Organization.state == state)

        total = await self.db.scalar(
            select(func.count()).select_from(Organization).where(*conditions)
        )
        result = await self.db.execute(
            select(Organization)
            .where(*conditions)
            .order_by(Organization.official_name)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

    async def _load_candidates(
        self,
        type_id: uuid.UUID | None,
        group_id: uuid.UUID | None = None,
    ) -> list[Organization]:
        """All non-deleted orgs (optionally scoped to one type or one whole
        group) — the pool the fuzzy matcher dedupes against. Includes
        'unverified' rows so we never create a duplicate of a row pending
        review."""
        conditions = [Organization.deleted_at.is_(None)]
        if type_id is not None:
            conditions.append(Organization.organization_type_id == type_id)
        if group_id is not None:
            conditions.append(
                Organization.organization_type_id.in_(self._group_type_subquery(group_id))
            )
        result = await self.db.execute(select(Organization).where(*conditions))
        return list(result.scalars().all())

    def _match(self, raw_name: str, existing: list[Organization]) -> Organization | None:
        """Exact-normalized match, then fuzzy match guarded by the divergent-
        suffix (tail) check. Returns the matched org or None."""
        target_key = _normalize(raw_name)
        target_tail = _tail(target_key)

        by_key: dict[str, Organization] = {}
        for org in existing:
            by_key[_normalize(org.official_name)] = org
            if org.short_name:
                by_key[_normalize(org.short_name)] = org

        # 1. Exact normalized match (official_name or short_name)
        if target_key in by_key:
            return by_key[target_key]

        # 2. Fuzzy match, guarded against divergent-suffix false merges
        candidates = difflib.get_close_matches(
            target_key, list(by_key.keys()), n=3, cutoff=FUZZY_CUTOFF
        )
        for candidate_key in candidates:
            if _similar(target_tail, _tail(candidate_key)) >= TAIL_CUTOFF:
                return by_key[candidate_key]
            # whole-string similar but distinguishing tail (campus/city)
            # diverges — treat as a different institution, keep checking.
        return None

    async def find_match(
        self,
        raw_name: str,
        *,
        type_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
    ) -> Organization | None:
        """Read-only resolution: does an existing org match this name? No row
        is ever created. Used by signup to decide found-vs-request. Scope to a
        single type (`type_id`) or a whole group (`group_id`)."""
        raw_name = (raw_name or "").strip()
        if not raw_name:
            return None
        return self._match(raw_name, await self._load_candidates(type_id, group_id))

    async def get_or_create(
        self, raw_name: str, *, type_id: uuid.UUID | None = None
    ) -> tuple[Organization, bool]:
        """Returns (organization, created). `created=True` means a brand-new,
        unverified row. Used by admin request-approval — NOT by the signup
        not-found path (that files a request instead)."""
        raw_name = (raw_name or "").strip()
        if not raw_name:
            raise ValueError("Organization name cannot be empty")

        existing = await self._load_candidates(type_id)
        match = self._match(raw_name, existing)
        if match is not None:
            return match, False

        new_org = Organization(
            official_name=raw_name,
            slug=_slugify(raw_name),
            organization_type_id=type_id,
            country="Nigeria",
            status="unverified",
            source_metadata={"source": "user_submitted"},
        )
        self.db.add(new_org)
        await self.db.flush()
        return new_org, True

    async def create_business(
        self,
        *,
        official_name: str,
        owner_user_id: uuid.UUID,
        type_id: uuid.UUID | None,
        state: str | None = None,
        pickup_address: str | None = None,
    ) -> Organization:
        """Create a Business-group organization owned by a user (signup as a
        business, or the 'Start selling' upgrade). Always a brand-new row —
        unlike universities, businesses aren't deduped against a curated list
        (two shops may legitimately share a name), so this never fuzzy-matches.
        Status is 'unverified'; an admin verifies businesses later."""
        org = Organization(
            official_name=official_name,
            slug=_slugify(official_name),
            organization_type_id=type_id,
            country="Nigeria",
            state=state,
            status="unverified",
            owner_user_id=owner_user_id,
            pickup_address=pickup_address,
            source_metadata={"source": "business_signup"},
        )
        self.db.add(org)
        await self.db.flush()
        return org

    async def get_owned_by_user(self, user_id: uuid.UUID) -> Organization | None:
        """The Business org this user owns, if any. Used to prompt a graduated
        seller to update their pickup address, and to guard against creating a
        second owned org on a redundant 'Start selling'."""
        result = await self.db.execute(
            select(Organization).where(
                Organization.owner_user_id == user_id,
                Organization.deleted_at.is_(None),
            )
        )
        return result.scalars().first()


class TaxonomyRepository:
    """Reads for the group/type lookup tables. Plain class (spans two models,
    so not a BaseRepository)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_groups(self) -> list[OrganizationGroup]:
        result = await self.db.execute(
            select(OrganizationGroup).order_by(OrganizationGroup.sort_order)
        )
        return list(result.scalars().all())

    async def get_group_by_slug(self, slug: str) -> OrganizationGroup | None:
        result = await self.db.execute(
            select(OrganizationGroup).where(OrganizationGroup.slug == slug)
        )
        return result.scalar_one_or_none()

    async def list_types(
        self, *, group_id: uuid.UUID | None = None
    ) -> list[OrganizationType]:
        stmt = select(OrganizationType).order_by(OrganizationType.sort_order)
        if group_id is not None:
            stmt = stmt.where(OrganizationType.organization_group_id == group_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_type_by_slug(self, slug: str) -> OrganizationType | None:
        result = await self.db.execute(
            select(OrganizationType).where(OrganizationType.slug == slug)
        )
        # slug is unique per-group, not globally; V1 slugs happen to be unique.
        # first() tolerates a future cross-group collision without raising.
        return result.scalars().first()


class OrganizationRequestRepository(BaseRepository[OrganizationRequest]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, OrganizationRequest)


class SignupRequestRepository(BaseRepository[SignupRequest]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, SignupRequest)

    async def list_pending_for_request(
        self, organization_request_id: uuid.UUID
    ) -> list[SignupRequest]:
        result = await self.db.execute(
            select(SignupRequest).where(
                SignupRequest.organization_request_id == organization_request_id,
                SignupRequest.status == "pending",
            )
        )
        return list(result.scalars().all())

    async def find_pending_by_email(self, email: str) -> SignupRequest | None:
        result = await self.db.execute(
            select(SignupRequest).where(
                SignupRequest.email == email, SignupRequest.status == "pending"
            )
        )
        return result.scalars().first()

    async def find_pending_by_username(self, username_normalized: str) -> SignupRequest | None:
        result = await self.db.execute(
            select(SignupRequest).where(
                SignupRequest.username_normalized == username_normalized,
                SignupRequest.status == "pending",
            )
        )
        return result.scalars().first()
