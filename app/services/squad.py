"""
Squad — the second gateway, server side only.

The same rule as Flutterwave, and for the same reason: the browser never decides
the price. The cart is `{slug, qty}`; `app/services/payments.py` prices it from
the catalogue and passes an amount here.

Two Squad-specific details live in this module so callers never have to remember
them:

* **Kobo.** Squad's `amount` is minor units — ₦4,200 is 420000. Every price in
  this app is whole naira, so the ×100 happens in `create_payment_link()` and the
  ÷100 in `verify_transaction()`, either side of the wire, and nothing else in
  the app has to think about kobo.

* **The webhook signature is an HMAC, not a shared secret in a header.**
  `x-squad-encrypted-body` is `HMAC-SHA512(raw_body, secret_key)` in uppercase
  hex. `verify_webhook_signature()` is the only place that computes it, and the
  router compares with `constant_time_compare` so a byte-by-byte timing signal
  cannot be used to guess it.

Errors carry no key material and no response body: Squad echoes the customer's
email back in error payloads, and that does not belong in a log line.
"""

import hashlib
import hmac
import logging
from decimal import Decimal

import httpx

from app.core.config import get_settings

logger = logging.getLogger("cartflow.squad")

settings = get_settings()

_TIMEOUT = 25.0

# Squad reports the outcome of a transaction in `transaction_status`.
_OK_STATUSES = {"success", "successful", "completed"}


class SquadError(Exception):
    """Squad could not be reached, or refused the call."""


def _headers() -> dict[str, str]:
    secret = settings.SQUAD_SECRET_KEY
    if not secret:
        raise SquadError("Squad is not configured (no secret key).")
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _base() -> str:
    return settings.SQUAD_API_BASE.rstrip("/")


def to_kobo(amount: Decimal) -> int:
    """₦4,200 → 420000. Rounded because a Decimal that is not exactly a naira
    (a future fee line, say) must still produce an integer on the wire."""
    return int((Decimal(amount) * 100).to_integral_value())


async def create_payment_link(
    *,
    reference: str,
    amount: Decimal,
    currency: str,
    redirect_url: str,
    customer: dict[str, str],
    title: str = "CartFlow",
) -> str:
    """Ask Squad for a hosted checkout URL for `reference`."""
    payload = {
        "amount": to_kobo(amount),
        "email": customer.get("email"),
        # `currency`, not `currency_code`: the server-side initiate endpoint takes
        # the short name (the modal's JS widget is the one that wants
        # `currency_code`). Sandbox rejects the wrong one with
        # `"currency_code" is not allowed`.
        "currency": currency,
        # `inline` returns a URL to send the browser to; the widget mode would
        # need the public key in the page, which is not how this checkout works.
        "initiate_type": "inline",
        "transaction_ref": reference,
        "callback_url": redirect_url,
        "customer_name": customer.get("name") or "",
        # The channels a Nigerian campus buyer actually has.
        # Only these four exist; "mobilemoney" (a Flutterwave channel) is not one.
        "payment_channels": ["card", "bank", "ussd", "transfer"],
        "metadata": {"integration": title, "reference": reference},
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_base()}/transaction/initiate", json=payload, headers=_headers()
            )
    except httpx.HTTPError as exc:
        raise SquadError("Could not reach Squad.") from exc

    body = response.json() if response.content else {}
    if response.status_code >= 400 or body.get("success") is False:
        logger.warning("squad initiate failed status=%s", response.status_code)
        message = body.get("message") if isinstance(body, dict) else None
        raise SquadError(f"Squad rejected the checkout ({message or response.status_code}).")

    data = body.get("data") or {}
    link = data.get("checkout_url") or data.get("checkout_url_v2")
    if not link:
        raise SquadError("Squad did not return a checkout link.")
    return str(link)


async def verify_transaction(reference: str) -> dict:
    """Squad's own record of `reference`, normalised for settlement.

        {"status", "amount", "currency", "provider_reference", "tx_ref"}

    `amount` is back in MAJOR units (₦) as a Decimal, matching `payments.amount`.
    `status` is `""` when Squad has no such transaction — a checkout the buyer
    opened and abandoned, which settlement treats as still pending.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{_base()}/transaction/verify/{reference}", headers=_headers()
            )
    except httpx.HTTPError as exc:
        raise SquadError("Could not reach Squad.") from exc

    if response.status_code >= 400:
        logger.info("squad verify status=%s ref=%s", response.status_code, reference)
        return {"status": "", "amount": None, "currency": None,
                "provider_reference": None, "tx_ref": reference}

    body = response.json() if response.content else {}
    data = body.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    raw_amount = data.get("transaction_amount")
    try:
        amount = (Decimal(str(raw_amount)) / 100) if raw_amount is not None else None
    except (ArithmeticError, ValueError):
        amount = None

    return {
        "status": str(data.get("transaction_status", "")).lower(),
        "amount": amount,
        "currency": str(data.get("transaction_currency_id") or data.get("currency") or ""),
        "provider_reference": (
            str(data.get("transaction_ref") or data.get("transaction_reference") or "")
            or None
        ),
        "tx_ref": reference,
    }


def is_success(status: str) -> bool:
    return status in _OK_STATUSES


def verify_webhook_signature(raw_body: bytes, supplied: str) -> bool:
    """True when `supplied` is the HMAC of the body keyed with the secret key.

    Squad sends the digest uppercase; case is normalised here rather than at the
    call site so a lowercase header from a proxy does not read as forged.
    """
    secret = settings.SQUAD_SECRET_KEY
    if not secret or not supplied:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, supplied.strip().lower())
