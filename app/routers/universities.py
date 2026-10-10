"""
University search + resolve endpoints — DEPRECATED thin aliases.

These delegate to the organization service (scoped to type=university) so the
existing frontend contract keeps working after the V1 pivot to organizations
(spec items #1/#2). Prefer /api/organizations/* for anything new; this router
will be removed once no client depends on it.

Behaviour change worth noting: /resolve is now READ-ONLY (it no longer creates
an unverified row on a miss). On no match it returns `created=false` with a
null university, mirroring /api/organizations/resolve's `found=false` — the
not-found path is a request, filed via /api/organizations/requests, not a
silent insert. Existing callers that treated a miss as "created a new one"
should move to the organizations endpoints.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.university import (
    UniversityOut,
    UniversityResolveRequest,
    UniversityResolveResponse,
)
from app.services import organization as org_service

router = APIRouter(prefix="/api/universities", tags=["universities (deprecated)"])

_TYPE_SLUG = "university"


def _to_university_out(org) -> UniversityOut:
    """Map an Organization onto the legacy University response shape."""
    return UniversityOut(
        id=org.id,
        official_name=org.official_name,
        short_name=org.short_name,
        state=org.state,
        institution_type=org.institution_type,
        status=org.status,
    )


@router.get("/search", response_model=list[UniversityOut], deprecated=True)
async def search_universities(
    q: str = Query(..., min_length=1, description="Partial university name"),
    db: AsyncSession = Depends(get_db),
):
    orgs = await org_service.search_autocomplete(
        db, q, type_slug=_TYPE_SLUG, limit=10
    )
    return [_to_university_out(o) for o in orgs]


@router.post("/resolve", response_model=UniversityResolveResponse, deprecated=True)
async def resolve_university(
    payload: UniversityResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    org, found = await org_service.resolve_organization(
        db, payload.name, type_slug=_TYPE_SLUG
    )
    return UniversityResolveResponse(
        university=_to_university_out(org) if org else None,
        created=False,  # read-only now: a miss files a request, not a row
    )
