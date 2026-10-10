"""
Business Hub endpoints — the seller's own business.

    GET    /api/business/profile   read the business you own
    PATCH  /api/business/profile   edit name / state / pickup address

Doc 16 §31 lists nine endpoints (dashboard, analytics, orders, products,
events, finance, location, status, pickups). Eight of them read or write tables
that do not exist — `businesses`, `business_locations`, `business_status`,
`business_analytics`, `inventory` (§30) are all unbuilt, as are products,
orders and events. Shipping them now would mean inventing numbers, so this
module exposes only what `organizations` can actually answer:

  - the business a user owns, resolved through `owner_user_id`;
  - the three editable columns on it.

The one thing this fixes rather than defers is the pickup-address dead-end.
`create_business` accepts `pickup_address` at signup and `set_graduation`
returns `needs_pickup_update=True` to tell a graduated seller their campus
pickup point probably moved — but nothing anywhere could write the new value.
Now the Hub can.

Ownership, not `is_seller`, is the gate: both routes go through
`account_service.get_owned_business`, which reads the org row. A signed-in
account with no business gets 404 (`NotFoundError`), which is also what
`is_seller=True` with no row would get — the flag can drift, the row can't.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.organization import (
    BusinessProfileOut,
    BusinessProfileResponse,
    BusinessProfileUpdateRequest,
)
from app.services import account as account_service

router = APIRouter(prefix="/api/business", tags=["business"])


@router.get("/profile", response_model=BusinessProfileOut)
async def get_business_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The business the caller owns. `get_current_user` (strict) rather than the
    optional dependency — this describes a private row to its owner, so no
    session means 401, never an anonymous read."""
    org = await account_service.get_owned_business(db, current_user)
    return BusinessProfileOut.model_validate(org)


@router.patch("/profile", response_model=BusinessProfileResponse)
async def update_business_profile(
    payload: BusinessProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit the business. Partial by design: `exclude_unset` means the Hub can
    submit just the pickup address without also having to resend the name, and
    an explicit `null` clears a field instead of being confused with "unchanged".

    There is no path here to another account's business — the row is looked up
    *from* the caller, never from an id in the request body, so no ownership
    check can be forgotten or bypassed."""
    org = await account_service.update_business_profile(
        db,
        current_user,
        changes=payload.model_dump(exclude_unset=True),
    )
    return BusinessProfileResponse(
        message="Business details saved.",
        business=BusinessProfileOut.model_validate(org),
    )
