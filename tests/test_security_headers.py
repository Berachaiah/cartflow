"""
Security-header tests, with one job above the others: keep the CSP and the
templates in step.

The bug these exist to prevent shipped for real. The policy allowlisted
cdnjs.cloudflare.com — an origin base.html has never loaded anything from —
while omitting the three it does load from and every inline <script> on the
page. Nothing failed loudly: the response was a 200 with correct-looking HTML,
and the browser silently refused to run the Tailwind CDN, so every utility class
in the app stopped resolving and the page rendered as unstyled markup with the
splash skeleton still up (the script that dismisses it was inline, so it was
blocked too). It reads as a broken server, which is why nobody suspected a
header.

The assertions here were therefore deliberately not "the CSP equals this string"
— that would just pin the bug in place. They walked the ACTUAL rendered HTML,
pulled out every external subresource, and checked the policy permitted it.

That framing has since been overtaken by something stronger. The app no longer
loads ANY external subresource: Tailwind is compiled to a static file, the fonts
are vendored by scripts/vendor_fonts.py, and Twemoji — the last one — was removed
after its pinned URL turned out to 404. So the two directional tests below both
assert zero rather than agreement, which is a property that cannot drift out of
step because there is nothing left to be out of step with. Both were inverted
rather than deleted, and both say in their own docstrings what to do when they
fail: vendor it, don't allowlist it.

Note what this does NOT cover. img-src still carries a bare `https:`, because
product photography and avatars come from Cloudinary at runtime and cannot be
vendored. A page therefore still needs the network to show its images — it just
no longer needs the network to render.
"""

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.middleware import SecurityHeadersMiddleware

CSP = SecurityHeadersMiddleware._CSP
TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"

# Public pages that all extend base.html, so the shared <head> is covered, plus
# enough page-specific markup to catch a template adding its own CDN.
PAGES = ["/", "/login", "/orders"]

_SCRIPT_SRC = re.compile(r'<script[^>]+src="https://([^/?"]+)')
_STYLESHEET = re.compile(
    r'<link(?=[^>]*rel="stylesheet")[^>]*href="https://([^/?"]+)', re.IGNORECASE
)


# --- nothing external, in either direction -------------------------------

@pytest.mark.parametrize("path", PAGES)
async def test_no_page_loads_an_external_script(client: AsyncClient, path: str):
    """Inverted, not deleted — the twin of the stylesheet test below.

    This asserted the opposite for most of its life: that every <script src> the
    page pulled in was permitted by script-src. That was the assertion that would
    have caught the Tailwind CDN being blocked, and it earned its keep.

    There is now nothing external left to permit. Tailwind is compiled to
    static/css/tailwind.css, the fonts are vendored, and the last one — Twemoji
    from cdn.jsdelivr.net — was removed once that pinned URL turned out to 404
    (upstream repo archived). It had been dead for some time without anyone
    noticing, because it was written as a progressive enhancement and no-opped
    exactly as designed. That is a good failure mode and a bad thing to leave in
    place: a request on every page load that can only 404.

    So the correct assertion is the stronger one — zero external scripts, and no
    third-party origin in script-src at all. If this fails because someone added
    a CDN, the fix is to vendor it (scripts/vendor_fonts.py is the worked
    example) or to host it from 'self', not to allowlist it. A dependency that
    only works online is a dependency that fails on the train.
    """
    r = await client.get(path)
    assert r.status_code == 200, r.text
    hosts = sorted(set(_SCRIPT_SRC.findall(r.text)))
    assert hosts == [], (
        f"{path} loads script(s) from {hosts} — every script is meant to be "
        "served from 'self' so the app works without internet access"
    )
    external = [s for s in CSP["script-src"] if s.startswith("https://")]
    assert external == [], (
        f"script-src still allowlists {external}, which no page references — "
        "dead weight in a policy is what this file exists to catch"
    )


@pytest.mark.parametrize("path", PAGES)
async def test_no_page_loads_an_external_stylesheet(client: AsyncClient, path: str):
    """Inverted, not deleted. This asserted the opposite until the fonts were
    vendored: that every external stylesheet the page pulled in was permitted by
    style-src, guarding the Google Fonts <link> whose blocking costs the display
    face and every Material Symbols icon.

    There is now no external stylesheet to guard. Tailwind is compiled to
    static/css/tailwind.css and the fonts to static/css/fonts.css, so the correct
    assertion is the stronger one — that the count is zero and style-src names no
    third-party host at all. Kept in this shape rather than removed because the
    property is worth defending: a CDN <link> added later would restore a
    dependency that a browser without internet cannot satisfy, and the failure
    mode is the one this file's module docstring describes — a 200, correct HTML,
    and a page that renders wrong for reasons no log mentions.

    If this fails because someone added a stylesheet host, the fix is to vendor
    it (scripts/vendor_fonts.py is the worked example), not to allowlist it.
    """
    r = await client.get(path)
    assert r.status_code == 200, r.text
    hosts = sorted(_STYLESHEET.findall(r.text))
    assert hosts == [], (
        f"{path} loads stylesheet(s) from {hosts} — every stylesheet is meant to "
        "be served from 'self' so the app renders without internet access"
    )
    external = [s for s in CSP["style-src"] if s.startswith("https://")]
    assert external == [], (
        f"style-src still allowlists {external}, which no page references — dead "
        "weight in a policy is what this file exists to catch"
    )


async def test_inline_scripts_are_permitted_while_the_page_still_has_them(
    client: AsyncClient,
):
    """The page cannot boot without its inline scripts, so the policy must allow
    them for exactly as long as they exist.

    Both halves are asserted together on purpose. Dropping 'unsafe-inline' while
    the blocks are still there silently breaks the theme bootstrap and the
    skeleton dismissal — a dark, half-painted page with no error to explain it.

    The obstacle to removing it is gone. It was here partly because the Tailwind
    Play CDN needed its inline `tailwind.config`, and a CDN that injects its own
    scripts cannot be nonced; both are retired, and script-src is now 'self' plus
    this. What remains is ordinary work: give the five inline blocks a nonce. So
    if this test fails because the count hit zero, the fix is to tighten
    script-src, not to loosen the test.
    """
    body = (await client.get("/login")).text
    inline_count = body.count("<script>")
    assert inline_count > 0, "no inline scripts left — tighten script-src instead"
    assert "'unsafe-inline'" in CSP["script-src"], (
        f"{inline_count} inline <script> blocks would be blocked"
    )


async def test_img_src_allows_the_pre_upload_photo_preview():
    """profile.html and settings.html call URL.createObjectURL to show a chosen
    photo before it is uploaded. Without blob: the preview is a broken image at
    the exact moment the user is deciding whether to keep the picture."""
    assert "blob:" in CSP["img-src"]
    users = [
        p.name
        for p in TEMPLATES.glob("*.html")
        if "createObjectURL" in p.read_text(encoding="utf-8")
    ]
    assert users, "no template previews an upload any more — blob: can go"


# --- the reverse: nothing allowlisted that nothing uses ------------------

def test_no_allowlisted_origin_is_unused():
    """The other direction of drift, and the one that hid the bug: cdnjs was
    allowlisted for so long that the policy looked deliberate. An origin no
    template names is either a leftover or a mistake, and both should fail.

    This passes vacuously today — there are no allowlisted origins left in any
    directive. Kept anyway, and kept SEPARATE from the two tests above, because
    it covers all of them: those two check script-src and style-src only, so an
    origin added to font-src or connect-src would slip past both and be caught
    only here.
    """
    rendered = "\n".join(
        p.read_text(encoding="utf-8") for p in TEMPLATES.rglob("*.html")
    )
    allowlisted = {
        source
        for sources in CSP.values()
        for source in sources
        if source.startswith("https://")
    }
    unused = {origin for origin in allowlisted if origin not in rendered}
    assert not unused, f"allowlisted but referenced by no template: {sorted(unused)}"


# --- the rest of the baseline -------------------------------------------

async def test_baseline_headers_present(client: AsyncClient):
    r = await client.get("/login")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = r.headers["content-security-policy"]
    # Directives that should never need widening: the app makes only same-origin
    # fetches, frames nothing, and posts nowhere else.
    assert "connect-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "form-action 'self'" in csp


async def test_no_hsts_outside_production(client: AsyncClient):
    """HSTS is remembered per host for the max-age, so sending it from a dev box
    would pin http://192.168.0.4:8000 to https for two years and break LAN phone
    testing with no visible cause. Tests run with APP_ENV=development."""
    r = await client.get("/login")
    assert "strict-transport-security" not in r.headers
