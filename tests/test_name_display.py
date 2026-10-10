"""
Long names must show in full.

The report: "in the home feed, like Sneaker Lab, it's a long name and it's
getting cut to 'Sneaker ....'....that's not right, please find a way for it to
show fully".

`truncate` was the reflex everywhere a string might not fit — and it is the
wrong reflex for a *name*. A name is not abbreviatable: "Sneaker …" is not a
short way of writing SneakerLab, it is a different shop. The same one line of
CSS was clipping university names on Discover, product names in the Shop rail,
the display name in the sidebar profile card and the business name at the top of
its own dashboard. Every one of them looked deliberate.

The rule this file enforces:

    A heading may carry `truncate` only if what it prints is a fixed string, or
    an identifier whose full value is already visible elsewhere on the screen.

Everything else wraps (`break-words`) or clamps to two lines (`line-clamp-2`).
Clamping is the ceiling, not the first resort — a row growing 14px taller costs
far less than a name nobody can read.

The `truncate` that remains on *sub*-lines is deliberate and stays: "@handle ·
2h · Bells University" genuinely is abbreviatable, and that is exactly the split
Instagram uses — the name wraps, the meta line clips.
"""

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")

_HEADING = re.compile(r"<(h[1-4])\s[^>]*class=\"([^\"]*)\"[^>]*>(.{0,120})", re.DOTALL)

# Headings allowed to clip, each with the reason it is not a name.
#
# Keyed by a snippet of what the heading prints, so adding a new clipped heading
# fails the test rather than quietly joining the list.
ALLOWED = {
    "{{ page_title }}": (
        "base.html's desktop-only page title. The values are fixed strings the app "
        "chooses ('Orders', 'Discover'), and `hidden lg:block` means it only ever "
        "renders where there is room for them"
    ),
    "{{ title }}": (
        "shop.html's section heading. The titles are literals in the template "
        "('Trending Now', 'Fresh Arrivals'), not user data"
    ),
    "Settings": "a literal.",
    "Shop": "a literal.",
    "@{{ profile_user.username }}": (
        "the profile top bar. A handle is capped at 30 characters by the schema, this "
        "is a fixed-height sticky bar that cannot grow a second line, and the identity "
        "row immediately below prints the same handle and the display name in full — so "
        "the clipped copy is never the only copy"
    ),
}


def _clipped_headings() -> list[tuple[str, int, str]]:
    """(file, line, printed content) for every heading carrying `truncate`."""
    out = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        src = path.read_text(encoding="utf-8")
        for m in _HEADING.finditer(src):
            if "truncate" not in m.group(2).split():
                continue
            line = src.count("\n", 0, m.start()) + 1
            out.append((path.name, line, m.group(3).strip()))
    return out


def test_no_name_heading_is_clipped():
    unexplained = []
    for name, line, content in _clipped_headings():
        if not any(key in content for key in ALLOWED):
            unexplained.append(f"{name}:{line} → {content.splitlines()[0][:60]}")
    assert not unexplained, (
        "these headings clip their content and are not on the allowlist in this file:\n  "
        + "\n  ".join(unexplained)
        + "\n\nA name is not abbreviatable — 'Sneaker …' is a different shop from "
        "SneakerLab. Use `break-words` to wrap, or `line-clamp-2` to cap at two lines. "
        "If the heading really does print a fixed string, add it to ALLOWED with the reason."
    )


@pytest.mark.parametrize(
    "path,heading_of",
    [
        ("/", "the feed's post author, story labels and Trending Brands"),
        ("/discover", "university and business cards"),
        ("/marketplace", "product cards and rails"),
    ],
)
async def test_pages_render_names_without_clipping(client: AsyncClient, path: str, heading_of: str):
    """The rendered check, so a macro that reintroduces `truncate` is caught too."""
    r = await client.get(path, follow_redirects=True)
    assert r.status_code == 200, r.text
    offenders = [
        m.group(0)[:110]
        for m in re.finditer(r"<h[1-4]\s[^>]*class=\"([^\"]*)\"[^>]*>", r.text)
        if "truncate" in m.group(1).split()
    ]
    # Only the allowlisted fixed-string titles may survive rendering.
    for o in offenders:
        assert "hidden lg:block" in o or "font-display text-[15px]" in o, (
            f"{path} renders a clipped heading ({heading_of}): {o}"
        )


def test_line_clamp_is_available_app_wide():
    """The utility the wrapping fix depends on has to exist everywhere.

    Tailwind's Play CDN build ships no line-clamp plugin, so `.line-clamp-2` is a
    hand-written rule. It used to live in shop.html, which meant every other page
    silently got no clamping at all — the class was there in the markup and did
    nothing, which is worse than not using it.
    """
    for n in (1, 2, 3):
        assert f".line-clamp-{n}" in BASE, (
            f".line-clamp-{n} is not declared in base.html. The CDN build has no "
            "line-clamp plugin, so the class is inert on every page that isn't shop.html"
        )
    assert "-webkit-line-clamp:2" in BASE, "the clamp rule lost its line count"
    others = [
        p.name for p in TEMPLATES.rglob("*.html")
        if p.name != "base.html" and "-webkit-line-clamp" in p.read_text(encoding="utf-8")
    ]
    assert not others, (
        f"line-clamp is redeclared in {others}. One declaration, in base.html — two "
        "copies drift and the page-local one wins by accident"
    )


async def test_the_post_author_wraps_rather_than_clips(client: AsyncClient):
    """The exact heading from the report, by name."""
    r = await client.get("/")
    assert "SneakerLab" in r.text, "the sample post used in the report is gone"
    author = re.search(
        r"<h3 class=\"([^\"]*)\"[^>]*>\s*SneakerLab", r.text
    )
    assert author, "could not find SneakerLab's heading in the rendered feed"
    tokens = author.group(1).split()
    assert "truncate" not in tokens, "the reported bug is back: the post author clips again"
    assert "break-words" in tokens, (
        "the author heading needs break-words, or a single long unspaced name "
        "('CampusTechStoreNigeria') overflows the card instead of wrapping"
    )


async def test_the_meta_line_still_clips(client: AsyncClient):
    """The other half of the rule: sub-lines are abbreviatable and should clip.

    Without this, a well-meaning sweep of `truncate` would turn "@sneakerlab · 5h ·
    Ota, Ogun" into two or three wrapped lines on every post and push the photo
    down the screen.
    """
    r = await client.get("/")
    meta = re.search(r"<p class=\"([^\"]*)\"[^>]*>@sneakerlab", r.text)
    assert meta, "the post meta line moved or changed shape"
    assert "truncate" in meta.group(1).split(), (
        "the @handle · time · location line should still truncate — it is context, not a "
        "name, and wrapping it costs vertical space on every post in the feed"
    )
