"""
Flutterwave — the gateway, server side only.

Two calls and one rule.

THE RULE: the browser never decides the price. The cart lives in localStorage
(`static/js/cartflow-cart.js`) and stores nothing but `{slug, qty}`. The amount
sent to Flutterwave is computed in `app/services/payments.py` from the
catalogue, so editing the cart in DevTools changes what is asked for, never what
is charged.

THE TWO CALLS:
  * `create_payment_link()` — POST /payments. Flutterwave answers with a hosted
    checkout URL; the browser is redirected there and the card data never
    touches this app.
  * `verify_transaction()` — GET /transactions/verify_by_reference. A redirect
    back with `?status=successful` proves only that the browser came back: that
    query string is attacker-controlled, so a payment is marked paid on the
    provider's verified answer and on nothing else.

The secret key lives here and nowhere else. Nothing in this module is imported
by a template, and errors raised out of it carry no key material — callers turn
them into a generic 502.
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger("cartflow.flutterwave")

settings = get_settings()

# Long enough for mobile-money confirmations, short enough that a hung provider
# does not hold a request worker for a minute.
_TIMEOUT = 20.0

# Flutterwave reports success in `status` as well as HTTP 200, so both are checked.
_OK_STATUSES = {"successful", "completed"}


class FlutterwaveError(Exception):
    """Flutterwave could not be reached, or refused the call.

    Deliberately message-only: no response body is embedded, because Flutterwave
    echoes request context (including the customer's email) back in errors and
    that does not belong in a log line or a 502 detail.
    """


def _headers() -> dict[str, str]:
    secret = settings.FLUTTERWAVE_SECRET_KEY
    if not secret:
        raise FlutterwaveError("Flutterwave is not configured (no secret key).")
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _base() -> str:
    return settings.FLUTTERWAVE_API_BASE.rstrip("/")


async def create_payment_link(
    *,
    reference: str,
    amount: str,
    currency: str,
    redirect_url: str,
    customer: dict[str, str],
    title: str = "CartFlow",
) -> str:
    """Ask Flutterwave for a hosted checkout URL for `reference`.

    `amount` arrives already formatted as a string with two decimals — floats do
    not survive a round trip through JSON and back into a money column intact.
    """
    payload = {
        "tx_ref": reference,
        "amount": amount,
        "currency": currency,
        "redirect_url": redirect_url,
        # The channels a Nigerian campus buyer actually has. Card is first
        # because it is what most people expect when they see "pay".
        "payment_options": "card,banktransfer,ussd,mobilemoney",
        "customer": customer,
        "customizations": {
            "title": title,
            "description": f"CartFlow order {reference}",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_base()}/payments", json=payload, headers=_headers()
            )
    except httpx.HTTPError as exc:
        raise FlutterwaveError("Could not reach Flutterwave.") from exc

    if response.status_code >= 400:
        logger.warning("flutterwave create failed status=%s", response.status_code)
        raise FlutterwaveError(
            f"Flutterwave rejected the checkout (HTTP {response.status_code})."
        )

    body = response.json() if response.content else {}
    if str(body.get("status", "")).lower() != "success":
        raise FlutterwaveError("Flutterwave did not return a checkout link.")

    link = (body.get("data") or {}).get("link")
    if not link:
        raise FlutterwaveError("Flutterwave did not return a checkout link.")
    return str(link)


async def verify_transaction(reference: str) -> dict:
    """The provider's verdict on `reference`.

    Returns the four fields settlement needs, lowercased and already
    normalised, so the service does not have to know Flutterwave's vocabulary:

        {"status", "amount", "currency", "provider_reference", "tx_ref"}

    `status` is `""` when Flutterwave has no transaction for the reference —
    a checkout that was abandoned before any payment was attempted.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_base()}/transactions/verify_by_reference",
                params={"tx_ref": reference},
                headers=_headers(),
            )
    except httpx.HTTPError as exc:
        raise FlutterwaveError("Could not reach Flutterwave.") from exc

    if response.status_code >= 400:
        # A 404 here means "no such transaction", not a broken integration:
        # the buyer opened checkout and closed it. Settlement treats it as
        # "still pending" rather than an error.
        logger.info("flutterwave verify status=%s ref=%s", response.status_code, reference)
        return {"status": "", "amount": None, "currency": None,
                "provider_reference": None, "tx_ref": reference}

    body = response.json() if response.content else {}
    data = body.get("data") or {}
    return {
        "status": str(data.get("status", "")).lower(),
        "amount": data.get("amount"),
        "currency": data.get("currency"),
        "provider_reference": str(data.get("id")) if data.get("id") else None,
        "tx_ref": data.get("tx_ref") or reference,
    }


def is_success(status: str) -> bool:
    return status in _OK_STATUSES
