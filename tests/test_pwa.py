"""Installability — the manifest, the service worker and their root URLs.

A PWA is mostly three files being served correctly, and every one of them fails
silently when it is not: a manifest at the wrong path is simply not found, and a
worker under `/static/` registers successfully while controlling nothing. So the
testable part is the delivery, not the browser behaviour: correct path, correct
content type, a `start_url`, and icons whose files exist.
"""

from httpx import AsyncClient


async def test_the_manifest_is_served_from_the_root(client: AsyncClient):
    r = await client.get("/manifest.webmanifest")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/manifest+json")

    manifest = r.json()
    assert manifest["start_url"], "a manifest with no start_url is not installable"
    assert manifest["display"] in {"standalone", "fullscreen", "minimal-ui"}
    assert manifest["name"] and manifest["short_name"]


async def test_every_declared_icon_exists(client: AsyncClient):
    """A 192 and a 512 are what browsers require before offering install, and a
    path that 404s is worse than no icon: it fails the check quietly."""
    manifest = (await client.get("/manifest.webmanifest")).json()
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes, sizes

    for icon in manifest["icons"]:
        r = await client.get(icon["src"])
        assert r.status_code == 200, icon["src"]
        assert r.headers["content-type"].startswith("image/png")


async def test_the_service_worker_is_served_from_the_root(client: AsyncClient):
    """Root, not /static: scope follows the script's URL."""
    r = await client.get("/sw.js")
    assert r.status_code == 200, r.text
    assert "javascript" in r.headers["content-type"]
    assert r.headers.get("service-worker-allowed") == "/"

    body = r.text
    assert "addEventListener('install'" in body
    assert "addEventListener('fetch'" in body


async def test_pages_link_the_manifest_and_register_the_worker(client: AsyncClient):
    body = (await client.get("/")).text
    assert 'rel="manifest" href="/manifest.webmanifest"' in body
    assert "navigator.serviceWorker.register('/sw.js')" in body
