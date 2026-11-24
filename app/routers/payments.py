"""
Payment endpoints: start a checkout, receive the redirect back, take webhooks.

Three routes, each with one job:

  POST /api/payments/checkout      the Shop's Checkout button. Prices the cart
                                   server-side, creates the pending row, and
                                   returns Flutterwave's hosted checkout URL.

  GET  /payments/callback          where Flutterwave sends the browser back.
                                   Verifies the reference server-side, then
                                   redirects to /orders with an honest result.
                                   The `status` query parameter Flutterwave adds
                                   is IGNORED — see the docstring on the route.

  POST /webhooks/flutterwave       the same settlement, server-to-server, so a
                                   buyer who closes the tab still gets a correct
                                   row. Authenticated by the `verif-hash` header.

Nothing here trusts the browser with money: the amount is computed from the
catalogue (app/services/payments.py), and a payment is only marked paid on the
provider's verified answer (app/services/flutterwave.py).
"""

import logging

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user, get_current_user_optional
from app.core.exceptions import ServiceUnavailableError
from app.core.security import constant_time_compare
from app.database.session import get_db
from app.models.user import User
from app.services import flutterwave, squad
from app.services import payments as payments_service

logger = logging.getLogger("cartflow.payments")

router = APIRouter(tags=["payments"])

settings = get_settings()


@router.post("/api/payments/checkout")
async def start_checkout(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Start a Flutterwave checkout for the cart the browser posted.

    The body is `{"items": [{"slug": "...", "qty": 2}]}` and NOTHING else — no
    names, no prices, no total. Every one of those is read from the catalogue
    here, which is what stops a hand-edited cart from becoming a hand-picked
    price.
    """
    try:
        payment = await payments_service.start_checkout(
            db,
            user=current_user,
            raw_items=payload.get("items"),
            provider=payload.get("provider"),
        )
    except (flutterwave.FlutterwaveError, squad.SquadError):
        # A refused or unreachable gateway is a 503 with a retryable message, not
        # a stack trace. The pending row (if it was committed) stays pending: no
        # money moved, and the reference is still there for a later attempt.
        logger.warning("checkout could not start: gateway error")
        raise ServiceUnavailableError(
            "That payment page could not be opened. Try the other payment method, "
            "or try again in a moment."
        )

    return {
        "reference": payment.reference,
        "provider": payment.provider,
        "checkout_url": payment.checkout_url,
        "amount": int(payment.amount),
        "currency": payment.currency,
    }


@router.get("/payments/callback")
async def payment_callback(
    tx_ref: str | None = None,
    # Squad returns its own parameter name. Both are read, neither is trusted:
    # the reference only identifies the row, and settlement asks the gateway.
    transaction_ref: str | None = None,
    status: str | None = None,  # noqa: ARG001 — deliberately unused, see below
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Flutterwave's return trip.

    `status` is accepted only so the URL does not 422 — it is NEVER read. It is a
    query parameter, so anyone can navigate to
    `/payments/callback?tx_ref=cf-…&status=successful` for a checkout they
    abandoned; settlement asks Flutterwave instead.

    The reference must belong to the signed-in viewer. Without that check a
    stranger could settle someone else's pending row (harmless data-wise, but it
    would also tell them the row exists).
    """
    tx_ref = tx_ref or transaction_ref
    if not tx_ref:
        return RedirectResponse("/orders", status_code=303)

    payment = await payments_service.by_reference(db, tx_ref)
    if payment is None:
        return RedirectResponse("/orders?payment=unknown", status_code=303)

    if current_user is None or payment.user_id != current_user.id:
        return RedirectResponse("/login?next=/orders", status_code=303)

    try:
        await payments_service.settle(db, payment=payment)
    except (flutterwave.FlutterwaveError, squad.SquadError):
        # The money may well have moved; we simply could not confirm it yet. The
        # row stays pending and the webhook (or a retry) will settle it.
        logger.warning("callback could not verify ref=%s", tx_ref)
        return RedirectResponse("/orders?payment=unconfirmed", status_code=303)

    return RedirectResponse(f"/orders?payment={payment.status}", status_code=303)


@router.post("/webhooks/flutterwave")
async def flutterwave_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Flutterwave's server-to-server notification.

    A webhook carries no signature of its own, so the `verif-hash` header is the
    entire authentication story: it must match the secret hash from the
    dashboard. Unset configuration refuses every call (401) rather than
    accepting unauthenticated "payment succeeded" posts to a public URL.

    Always answers 200 to an authentic call, including when the reference is
    unknown or the verify is briefly unavailable — a non-2xx makes Flutterwave
    retry the same event, and retrying will not fix an unknown reference.
    """
    expected = settings.FLUTTERWAVE_WEBHOOK_HASH
    supplied = request.headers.get("verif-hash") or ""
    if not expected or not supplied or not constant_time_compare(supplied, expected):
        logger.warning("flutterwave webhook rejected: bad or missing verif-hash")
        return JSONResponse({"status": "ignored"}, status_code=401)

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"status": "ignored"}, status_code=400)

    data = body.get("data") if isinstance(body, dict) else None
    reference = (data or {}).get("tx_ref") if isinstance(data, dict) else None
    if not reference:
        return JSONResponse({"status": "ignored"}, status_code=200)

    payment = await payments_service.by_reference(db, reference)
    if payment is None:
        # A charge for a reference we never minted: log it, acknowledge, move on.
        logger.warning("flutterwave webhook for unknown ref=%s", reference)
        return JSONResponse({"status": "ignored"}, status_code=200)

    try:
        await payments_service.settle(db, payment=payment)
    except (flutterwave.FlutterwaveError, squad.SquadError):
        logger.warning("webhook could not verify ref=%s", reference)
        return JSONResponse({"status": "deferred"}, status_code=200)

    return JSONResponse({"status": "ok", "reference": reference, "payment": payment.status})


@router.post("/webhooks/squad")
async def squad_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Squad's server-to-server notification.

    Authentication is an HMAC of the RAW body keyed with the secret key, echoed in
    `x-squad-encrypted-body`. The bytes must be hashed before any parsing, which
    is why this route reads `await request.body()` rather than calling
    `request.json()` first: re-serialising parsed JSON changes key order and
    whitespace, and the digest would never match.

    Squad nests the transaction under `Body` (`{"Event": ..., "Body": {...}}`),
    while older payloads put the fields at the top level; both are accepted.
    """
    raw = await request.body()
    supplied = request.headers.get("x-squad-encrypted-body") or ""
    if not squad.verify_webhook_signature(raw, supplied):
        logger.warning("squad webhook rejected: bad or missing signature")
        return JSONResponse({"status": "ignored"}, status_code=401)

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"status": "ignored"}, status_code=400)

    payload = body.get("Body") if isinstance(body, dict) and "Body" in body else body
    reference = (payload or {}).get("transaction_ref") if isinstance(payload, dict) else None
    if not reference:
        return JSONResponse({"status": "ignored"}, status_code=200)

    payment = await payments_service.by_reference(db, reference)
    if payment is None:
        logger.warning("squad webhook for unknown ref=%s", reference)
        return JSONResponse({"status": "ignored"}, status_code=200)

    try:
        await payments_service.settle(db, payment=payment)
    except (flutterwave.FlutterwaveError, squad.SquadError):
        logger.warning("squad webhook could not verify ref=%s", reference)
        return JSONResponse({"status": "deferred"}, status_code=200)

    return JSONResponse({"status": "ok", "reference": reference, "payment": payment.status})
