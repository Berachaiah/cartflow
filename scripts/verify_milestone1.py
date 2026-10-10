"""
Milestone-1 end-to-end verification (dev-only).

Drives the real ASGI app in-process against the local SQLite preview DB —
no server or network needed. Verifies the three new pages render and the
full signup journeys behave, including the deferred-request path.

Run:
    DATABASE_URL="sqlite+aiosqlite:///./dev_preview.db" \
        ./venv/bin/python scripts/verify_milestone1.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./dev_preview.db")

logging.disable(logging.CRITICAL)

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402

_ok = 0
_fail = 0


def check(cond: bool, label: str) -> None:
    global _ok, _fail
    print(f"[{'PASS' if cond else 'FAIL'}] {label}")
    if cond:
        _ok += 1
    else:
        _fail += 1


async def main() -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        print("--- pages render ---")
        for path in ("/signup", "/universities", "/request-organization"):
            r = await c.get(path)
            body = r.text
            leak = "{{" in body or "{%" in body
            check(r.status_code == 200 and not leak, f"GET {path} -> {r.status_code} ({len(body)} bytes)")
            check("cartflow-forms.js" in body, f"  {path} loads shared JS helper")
        check((await c.get("/static/js/cartflow-forms.js")).status_code == 200, "static JS is served")

        print("\n--- directory + pagination ---")
        page1 = (await c.get("/api/organizations?per_page=20")).json()
        check(page1["total"] == 32 and page1["pages"] == 2 and len(page1["items"]) == 20,
              f"page 1: total={page1['total']} pages={page1['pages']} items={len(page1['items'])}")
        page2 = (await c.get("/api/organizations?page=2&per_page=20")).json()
        check(len(page2["items"]) == 12, f"page 2 items={len(page2['items'])}")
        lagos = (await c.get("/api/organizations?state=Lagos")).json()
        check(lagos["total"] >= 1 and all(o["state"] == "Lagos" for o in lagos["items"]),
              f"state filter Lagos -> {lagos['total']}")

        print("\n--- JOURNEY A: existing university ---")
        orgs = (await c.get("/api/organizations/search?q=Unilag")).json()
        check(bool(orgs) and orgs[0]["short_name"] == "UNILAG",
              f"typeahead 'Unilag' -> {orgs[0]['official_name'] if orgs else 'none'}")
        r = await c.post("/api/auth/signup/student", json={
            "full_name": "Ada Lovelace", "username": "ada.l", "email": "ada@example.com",
            "password": "sup3rsecret!", "organization_id": orgs[0]["id"]})
        b = r.json()
        check(r.status_code == 201 and b["outcome"] == "account_created", f"signup -> {b.get('outcome')}")
        check(b["user"] and b["user"]["organization_id"] == orgs[0]["id"], "user linked to chosen org")

        print("\n--- JOURNEY B: unknown university -> deferred request ---")
        r = await c.post("/api/organizations/resolve", json={"name": "Zenith Global University"})
        check(r.json()["found"] is False, "resolve miss -> found=false (never silently creates)")
        r = await c.post("/api/organizations/requests", json={
            "requested_name": "Zenith Global University", "country": "Nigeria",
            "state": "Lagos", "type": "university"})
        check(r.status_code == 201 and r.json()["status"] == "pending", f"request filed -> {r.status_code}")
        r = await c.post("/api/auth/signup/student", json={
            "full_name": "Grace Hopper", "username": "grace", "email": "grace@example.com",
            "password": "sup3rsecret!", "organization_name": "Zenith Global University"})
        b = r.json()
        check(b["outcome"] == "pending_organization_review" and b["user"] is None,
              f"signup -> {b.get('outcome')}, user=None (no account until approved)")
        total = (await c.get("/api/organizations")).json()["total"]
        check(total == 32, f"no org silently created (total still {total})")

        print("\n--- JOURNEY C: errors the UI surfaces ---")
        r = await c.post("/api/auth/signup/student", json={
            "full_name": "Dup", "username": "dupuser", "email": "ada@example.com",
            "password": "sup3rsecret!", "organization_id": orgs[0]["id"]})
        check(r.status_code == 409, f"duplicate email -> {r.status_code}")
        check("error" in r.json() and "message" in r.json()["error"], "error envelope carries error.message")
        r = await c.post("/api/auth/signup/student", json={
            "full_name": "No Org", "username": "noorg", "email": "noorg@example.com",
            "password": "sup3rsecret!"})
        check(r.status_code == 422, f"missing organization -> {r.status_code}")

    print(f"\n{_ok} passed, {_fail} failed")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
