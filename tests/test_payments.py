"""
Flutterwave checkout — the money paths, and the rules that keep them honest.

Four invariants, in the order a shopper meets them:

  1. THE CLIENT CANNOT SET A PRICE. The cart posts `{slug, qty}` and the amount
     is re-read from the catalogue. A posted `price`/`line_total` is ignored.
  2. A SOLD-OUT LINE IS REFUSED, not silently dropped — charging for part of a
     cart is worse than refusing it.
  3. MONEY IS MARKED RECEIVED ONLY ON THE PROVIDER'S VERDICT. The callback's
     `?status=` parameter is a query string anyone can type, and the callback
     belongs to one buyer: another account settles nothing.
  4. THE WEBHOOK IS AUTHENTICATED by `verif-hash`. With no hash configured the
     endpoint refuses, because it is a public POST that says "payment succeeded".

Flutterwave itself is monkeypatched throughout — these tests must never touch
the network, and a test that needs a real card is not a test.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.payment import Payment
from app.models.product import Product
from app.services import payments as payments_service

PASSWORD = "Long-enough-pass-2026"


# --- helpers ----------------------------------------------------------

async def _signup(client: AsyncClient, username: str, **extra) -> None:
    payload = {
        "role": extra.pop("role", "individual"),
        "full_name": f"{username.title()} Tester",
        "username": username,
        "email": f"{username}@example.com",
        "password": PASSWORD,
        **extra,
    }
    r = await client.post("/api/auth/signup", json=payload)
    assert r.status_code == 201, r.text


async def _login(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def _product(client: AsyncClient, *, price: int = 11500, stock: int = 10) -> dict:
    """A seller with one live listing. Returns the product as the API sees it."""
    await _signup(client, "retrovibe", role="brand", business_name="RetroVibe Apparel", state="Lagos")
    await _login(client, "retrovibe")
    r = await client.post(
        "/api/business/products",
        json={
            "name": "Campus Tee",
            "category": "Fashion",
            "price": price,
            "stock": stock,
            "pickup_address": "Main Gate",
            "image_url": "https://example.com/tee.jpg",
            "image_alt": "An oversized tee",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["product"]


async def _buyer(client: AsyncClient, username: str = "buyer") -> None:
    await _signup(client, username)
    await _login(client, username)


@pytest.fixture
def gateway(monkeypatch):
    """A configured gateway that records what it was asked to charge."""
    monkeypatch.setattr(
        payments_service.settings, "FLUTTERWAVE_SECRET_KEY", "test-secret", raising=False
    )
    seen = {"amount": None, "reference": None}
    verdict = {
        "status": "successful",
        "amount": None,  # set to the charged amount so the check passes
        "currency": "NGN",
        "provider_reference": "987654",
        "tx_ref": None,
    }

    async def _create_link(**kwargs):
        seen["amount"] = kwargs["amount"]
        seen["reference"] = kwargs["reference"]
        verdict["amount"] = kwargs["amount"]
        verdict["tx_ref"] = kwargs["reference"]
        return f"https://checkout.flutterwave.test/{kwargs['reference']}"

    async def _verify(reference):
        return {**verdict, "tx_ref": reference}

    monkeypatch.setattr(payments_service.flutterwave, "create_payment_link", _create_link)
    monkeypatch.setattr(payments_service.flutterwave, "verify_transaction", _verify)
    return {"seen": seen, "verdict": verdict}


async def _checkout(client: AsyncClient, slug: str, qty: int = 1, **extra) -> dict:
    r = await client.post(
        "/api/payments/checkout", json={"items": [{"slug": slug, "qty": qty, **extra}]}
    )
    return r


# --- 1. the server prices the cart ------------------------------------

async def test_checkout_charges_the_catalogue_price_not_the_posted_one(
    client: AsyncClient, gateway
):
    """The reported bug class this endpoint exists to prevent.

    The browser sends a cart, and a cart is `{slug, qty}`. Even when a caller
    adds its own `price` and `line_total`, they are ignored: the amount asked of
    Flutterwave comes from the product row.
    """
    product = await _product(client, price=11500)
    await _buyer(client)

    r = await _checkout(client, product["slug"], qty=2, price=1, line_total=1)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 23000, "checkout used a price the client sent"
    assert gateway["seen"]["amount"] == "23000.00", (
        "the provider was asked to charge something other than 2 × ₦11,500"
    )
    assert body["checkout_url"].startswith("https://checkout.flutterwave.test/")


async def test_checkout_refuses_a_quantity_the_stock_cannot_cover(
    client: AsyncClient, gateway
):
    """A short stock is a refusal, not a quietly smaller cart."""
    product = await _product(client, stock=2)
    await _buyer(client)

    r = await _checkout(client, product["slug"], qty=5)

    # 422 is this app's VALIDATION_ERROR (see app/core/exceptions.py), not
    # FastAPI's default — the message is what the Shop's toast shows.
    assert r.status_code == 422, r.text
    assert "Only 2 left" in r.json()["error"]["message"]


async def test_checkout_requires_a_signed_in_buyer(client: AsyncClient, gateway):
    product = await _product(client)
    # Sign the seller out so the checkout call is anonymous.
    await client.post("/api/auth/logout")

    r = await _checkout(client, product["slug"])

    assert r.status_code == 401, r.text


# --- 3. the callback --------------------------------------------------

async def _payment_row(db, reference: str) -> Payment:
    """The row, read fresh — the checkout committed it, so another session sees it."""
    db.expire_all()
    return (
        await db.execute(select(Payment).where(Payment.reference == reference))
    ).scalar_one()


async def _stock_of(db, slug: str) -> int:
    db.expire_all()
    row = (await db.execute(select(Product).where(Product.slug == slug))).scalar_one()
    return row.stock


async def test_callback_settles_the_payment_and_takes_stock(
    client: AsyncClient, db, gateway
):
    """A verified payment is recorded, the stock moves once, and Orders shows it."""
    product = await _product(client, stock=10)
    await _buyer(client)
    reference = (await _checkout(client, product["slug"], qty=3)).json()["reference"]

    r = await client.get(f"/payments/callback?tx_ref={reference}&status=successful")

    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/orders?payment=successful"

    paid = await _payment_row(db, reference)
    assert paid.status == "successful"
    assert paid.provider_reference == "987654"
    assert await _stock_of(db, product["slug"]) == 7, "stock did not follow the sale"

    orders = await client.get("/orders")
    assert "Paid" in orders.text
    assert reference in orders.text


async def test_callback_ignores_a_status_parameter_with_no_payment(
    client: AsyncClient, db, gateway
):
    """`?status=successful` on an abandoned checkout settles nothing.

    Flutterwave has no transaction for the reference, so verification comes back
    empty and the row must stay pending even though the URL says successful.
    """
    product = await _product(client)
    await _buyer(client)
    reference = (await _checkout(client, product["slug"])).json()["reference"]

    gateway["verdict"]["status"] = ""
    r = await client.get(f"/payments/callback?tx_ref={reference}&status=successful")

    assert r.status_code == 303
    assert r.headers["location"] == "/orders?payment=pending"
    assert (await _payment_row(db, reference)).status == "pending"


async def test_callback_refuses_another_accounts_payment(client: AsyncClient, db, gateway):
    """One buyer's reference is not another buyer's to settle."""
    product = await _product(client)
    await _buyer(client, "first")
    reference = (await _checkout(client, product["slug"])).json()["reference"]

    await client.post("/api/auth/logout")
    await _buyer(client, "second")
    r = await client.get(f"/payments/callback?tx_ref={reference}&status=successful")

    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")
    assert (await _payment_row(db, reference)).status == "pending"


async def test_callback_rejects_a_mismatched_amount(client: AsyncClient, db, gateway):
    """A verified transaction for a different amount is not this receipt."""
    product = await _product(client, price=11500)
    await _buyer(client)
    reference = (await _checkout(client, product["slug"])).json()["reference"]

    gateway["verdict"]["amount"] = "50.00"
    await client.get(f"/payments/callback?tx_ref={reference}&status=successful")

    assert (await _payment_row(db, reference)).status == "pending"


# --- 4. the webhook ---------------------------------------------------

async def test_webhook_without_a_configured_hash_is_refused(client: AsyncClient, gateway):
    """A public POST that says "payment succeeded" is refused unless it is signed."""
    gateway["verdict"]["amount"] = "100.00"
    r = await client.post(
        "/webhooks/flutterwave",
        json={"data": {"tx_ref": "cf-whatever", "status": "successful"}},
        headers={"verif-hash": "anything"},
    )
    assert r.status_code == 401, r.text


async def test_webhook_settles_a_payment_it_was_told_about(
    client: AsyncClient, db, gateway, monkeypatch
):
    """With the hash configured, a wrong hash still fails and the right one settles."""
    product = await _product(client)
    await _buyer(client)
    reference = (await _checkout(client, product["slug"])).json()["reference"]
    monkeypatch.setattr(
        get_settings(), "FLUTTERWAVE_WEBHOOK_HASH", "real-hash", raising=False
    )

    bad = await client.post(
        "/webhooks/flutterwave",
        json={"data": {"tx_ref": reference, "status": "successful"}},
        headers={"verif-hash": "not-the-hash"},
    )
    assert bad.status_code == 401
    assert (await _payment_row(db, reference)).status == "pending"

    good = await client.post(
        "/webhooks/flutterwave",
        json={"data": {"tx_ref": reference, "status": "successful"}},
        headers={"verif-hash": "real-hash"},
    )
    assert good.status_code == 200, good.text
    assert good.json()["payment"] == "successful"
    assert (await _payment_row(db, reference)).status == "successful"


async def test_a_webhook_for_an_unknown_reference_is_acknowledged(
    client: AsyncClient, monkeypatch
):
    """Answer 200: a non-2xx makes Flutterwave retry an event we can never match."""
    monkeypatch.setattr(
        get_settings(), "FLUTTERWAVE_WEBHOOK_HASH", "real-hash", raising=False
    )
    r = await client.post(
        "/webhooks/flutterwave",
        json={"data": {"tx_ref": f"cf-{uuid.uuid4().hex}", "status": "successful"}},
        headers={"verif-hash": "real-hash"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


# --- 5. Squad, the second gateway -------------------------------------
#
# Squad differs from Flutterwave in two places worth a test each: the amount goes
# over the wire in kobo, and its webhook is authenticated by an HMAC of the raw
# body (there is no shared header value to configure).

@pytest.fixture
def squad_gateway(monkeypatch):
    """A configured Squad that records what it was asked to charge."""
    monkeypatch.setattr(
        payments_service.settings, "SQUAD_SECRET_KEY", "sandbox_sk_test", raising=False
    )
    seen: dict = {"amount": None, "reference": None}
    verdict = {
        "status": "success",
        "amount": None,
        "currency": "NGN",
        "provider_reference": "SQ-42",
        "tx_ref": None,
    }

    async def _create_link(**kwargs):
        seen["amount"] = kwargs["amount"]
        seen["reference"] = kwargs["reference"]
        verdict["amount"] = kwargs["amount"]
        return f"https://checkout.squad.test/{kwargs['reference']}"

    async def _verify(reference):
        return {**verdict, "tx_ref": reference}

    monkeypatch.setattr(payments_service.squad, "create_payment_link", _create_link)
    monkeypatch.setattr(payments_service.squad, "verify_transaction", _verify)
    return {"seen": seen, "verdict": verdict}


async def test_squad_checkout_records_the_chosen_provider(client: AsyncClient, squad_gateway):
    """The picker's value reaches the row, and the amount is still the catalogue's."""
    product = await _product(client, price=11500)
    await _buyer(client)

    r = await client.post(
        "/api/payments/checkout",
        json={"items": [{"slug": product["slug"], "qty": 2}], "provider": "squad"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "squad"
    assert body["checkout_url"].startswith("https://checkout.squad.test/")
    assert squad_gateway["seen"]["amount"] == 23000, "Squad was not charged ₦23,000"


async def test_squad_callback_settles_and_takes_stock(client: AsyncClient, db, squad_gateway):
    product = await _product(client, stock=6)
    await _buyer(client)
    reference = (
        await client.post(
            "/api/payments/checkout",
            json={"items": [{"slug": product["slug"], "qty": 2}], "provider": "squad"},
        )
    ).json()["reference"]

    # Squad's own redirect parameter name, and a made-up ?status= that must be
    # ignored exactly as Flutterwave's is.
    r = await client.get(
        f"/payments/callback?transaction_ref={reference}&status=successful"
    )

    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/orders?payment=successful"
    paid = await _payment_row(db, reference)
    assert paid.provider == "squad"
    assert paid.status == "successful"
    assert await _stock_of(db, product["slug"]) == 4


def test_squad_kobo_conversion_is_exact():
    """₦4,200 → 420000. A float would eventually lose a kobo on a naira amount;
    the service keeps the conversion in one place so nothing else has to try."""
    from decimal import Decimal

    from app.services import squad

    assert squad.to_kobo(Decimal("4200")) == 420000
    assert squad.to_kobo(Decimal("4200.50")) == 420050
    assert squad.to_kobo(Decimal("0")) == 0


async def test_an_unknown_provider_is_refused(client: AsyncClient, squad_gateway):
    """A provider string the deployment does not offer is a refusal, not a
    silent fallback to whichever gateway happens to be configured."""
    product = await _product(client)
    await _buyer(client)

    r = await client.post(
        "/api/payments/checkout",
        json={"items": [{"slug": product["slug"], "qty": 1}], "provider": "paystack"},
    )

    assert r.status_code == 422, r.text
    assert "not available" in r.json()["error"]["message"].lower()


async def test_squad_webhook_requires_a_valid_hmac(client: AsyncClient, db, squad_gateway, monkeypatch):
    """The signature is the whole authentication story for a public POST."""
    import hashlib
    import hmac
    import json as _json

    product = await _product(client)
    await _buyer(client)
    reference = (
        await client.post(
            "/api/payments/checkout",
            json={"items": [{"slug": product["slug"], "qty": 1}], "provider": "squad"},
        )
    ).json()["reference"]

    payload = _json.dumps(
        {"Event": "charge_successful", "Body": {"transaction_ref": reference, "transaction_status": "Success"}}
    ).encode()

    bad = await client.post(
        "/webhooks/squad",
        content=payload,
        headers={"x-squad-encrypted-body": "not-the-digest", "Content-Type": "application/json"},
    )
    assert bad.status_code == 401
    assert (await _payment_row(db, reference)).status == "pending"

    digest = hmac.new(b"sandbox_sk_test", payload, hashlib.sha512).hexdigest().upper()
    good = await client.post(
        "/webhooks/squad",
        content=payload,
        headers={"x-squad-encrypted-body": digest, "Content-Type": "application/json"},
    )
    assert good.status_code == 200, good.text
    assert good.json()["payment"] == "successful"
    assert (await _payment_row(db, reference)).status == "successful"
