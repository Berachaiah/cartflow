"""
Organization endpoints (spec item #22) — the canonical replacement for the
universities router.

Flow for signup (spec items #3-#7):
  1. GET  /api/organizations/search?q=...        typeahead, top-5 (item #3)
  2. GET  /api/organizations                     directory, filters + paging (item #4)
  3. POST /api/organizations/resolve             read-only: found? (item #6)
  4. POST /api/organizations/requests            file a request for a missing org (item #6)

Plus the taxonomy lookups (separate `taxonomy_router`, sibling paths):
  GET /api/organization-groups
  GET /api/organization-types[?group=<slug>]

Success bodies are returned bare (the {data, meta} envelope in Ch.12 sec 48
is applied to errors only, matching the existing universities router).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.organization import TaxonomyRepository
from app.schemas.organization import (
    OrganizationDirectoryPage,
    OrganizationGroupOut,
    OrganizationOut,
    OrganizationRequestCreate,
    OrganizationRequestOut,
    OrganizationResolveRequest,
    OrganizationResolveResponse,
    OrganizationTypeOut,
)
from app.services import organization as org_service

router = APIRouter(prefix="/api/organizations", tags=["organizations"])
taxonomy_router = APIRouter(prefix="/api", tags=["organizations"])


@router.get("/search", response_model=list[OrganizationOut])
async def search_organizations(
    q: str = Query(..., min_length=1, description="Partial organization name"),
    type: str | None = Query(
        default="university", description="Type slug to scope search to"
    ),
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Typeahead search — returns top-N matches (default 5, no total count)."""
    return await org_service.search_autocomplete(
        db, q, type_slug=type, limit=limit
    )


@router.get("", response_model=OrganizationDirectoryPage)
async def list_organizations(
    country: str | None = Query(default=None),
    state: str | None = Query(default=None),
    type: str | None = Query(default=None, description="Type slug filter"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Paginated directory with country/state/type filters (spec item #4)."""
    orgs, total, pages = await org_service.list_directory(
        db,
        country=country,
        state=state,
        type_slug=type,
        page=page,
        per_page=per_page,
    )
    return OrganizationDirectoryPage(
        items=[OrganizationOut.model_validate(o) for o in orgs],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post("/resolve", response_model=OrganizationResolveResponse)
async def resolve_organization(
    payload: OrganizationResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Read-only: does a matching org already exist? Never creates a row —
    the not-found path files a request instead (spec item #6)."""
    org, found = await org_service.resolve_organization(
        db, payload.name, type_slug=payload.type
    )
    return OrganizationResolveResponse(
        organization=OrganizationOut.model_validate(org) if org else None,
        found=found,
    )


@router.post("/requests", response_model=OrganizationRequestOut, status_code=201)
async def create_organization_request(
    payload: OrganizationRequestCreate,
    db: AsyncSession = Depends(get_db),
):
    """File a request for an organization we don't have yet (spec item #6)."""
    request = await org_service.create_organization_request(
        db,
        requested_name=payload.requested_name,
        country=payload.country,
        state=payload.state,
        type_slug=payload.type,
    )
    return OrganizationRequestOut.model_validate(request)


@taxonomy_router.get("/organization-groups", response_model=list[OrganizationGroupOut])
async def list_organization_groups(db: AsyncSession = Depends(get_db)):
    repo = TaxonomyRepository(db)
    return await repo.list_groups()


@taxonomy_router.get("/organization-types", response_model=list[OrganizationTypeOut])
async def list_organization_types(
    group: str | None = Query(default=None, description="Group slug filter"),
    db: AsyncSession = Depends(get_db),
):
    repo = TaxonomyRepository(db)
    group_id = None
    if group:
        group_obj = await repo.get_group_by_slug(group)
        if group_obj:
            group_id = group_obj.id
    return await repo.list_types(group_id=group_id)
