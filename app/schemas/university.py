"""University-related request/response schemas."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class UniversityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    official_name: str
    short_name: str | None = None
    state: str | None = None
    institution_type: str | None = None
    status: str


class UniversityResolveRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class UniversityResolveResponse(BaseModel):
    # `university` is null when nothing matched — the deprecated /resolve is
    # read-only now (a miss files a request via /api/organizations/requests
    # rather than creating a row), so `created` is always False here.
    university: UniversityOut | None = None
    created: bool
