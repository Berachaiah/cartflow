"""
Vendored-asset integrity: the app must render without reaching the internet.

Every visual thing in CartFlow used to be a third-party fetch — Tailwind compiled
in the browser by cdn.tailwindcss.com, and three font families from Google. That
made the styling only as reliable as the viewer's route to two CDNs, and the
failure was ugly out of proportion to its cause: a phone on a hotspot with no
upstream got default serif text, blue underlined links, and — because Material
Symbols renders through ligatures — the icon NAMES printed as English words, so
the navigation read "home Home explore Discover storefront Shop".

Both are now built or downloaded into app/static. These tests defend the part of
that which can rot silently:

  1. FONTS.CSS MUST NOT OUTLIVE ITS FILES. It is generated, listing 52 @font-face
     blocks across 11 woff2 files. Delete one file, or half-run the script, and
     nothing errors — the browser gets a 404 for one unicode-range subset and
     falls back. For Material Symbols that means icons silently become words
     again, which is the exact bug this all exists to remove.
  2. NOTHING MAY POINT BACK AT GOOGLE. A single un-rewritten url() reintroduces
     the dependency for whichever subset it covers, and it would be invisible
     anywhere with working internet — including every machine a developer uses.
  3. THE LIGATURE RULE IS LOAD-BEARING AND NOT OURS. `.material-symbols-outlined`
     comes from Google's stylesheet, not cartflow-ui.css (which only overrides
     font-size). Regenerating without it, or hand-editing fonts.css, drops the
     'liga' feature setting and the icons become words with the font present.
  4. THE COMPILED STYLESHEET MUST EXIST AND CARRY THE THEME. Tailwind is no
     longer a script that compiles whatever it finds; it is a file, and a missing
     or truncated one is a wholly unstyled app.

What these CANNOT catch is staleness — a template gaining a class that nobody
rebuilt for. That needs the compiler, so it stays a discipline documented in
tailwind-input.css rather than an assertion here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
FONTS_CSS = STATIC / "css" / "fonts.css"
TAILWIND_CSS = STATIC / "css" / "tailwind.css"

_URL = re.compile(r"url\(([^)]+)\)")


def _font_css() -> str:
    assert FONTS_CSS.exists(), (
        "app/static/css/fonts.css is missing — run scripts/vendor_fonts.py"
    )
    return FONTS_CSS.read_text(encoding="utf-8")


# --- fonts ---------------------------------------------------------------

def test_every_font_url_resolves_to_a_file_on_disk():
    """A url() with no file behind it is a 404 the browser handles by falling
    back, so the page still renders and the icons quietly stop being icons."""
    css = _font_css()
    refs = {u.strip("\"'") for u in _URL.findall(css)}
    assert refs, "fonts.css references no font files — the rewrite step failed"

    missing = []
    for ref in refs:
        assert ref.startswith("/static/fonts/"), (
            f"unexpected font URL {ref!r} — expected a /static/fonts/ path"
        )
        if not (STATIC / ref[len("/static/") :]).is_file():
            missing.append(ref)

    assert not missing, (
        f"fonts.css references {len(missing)} file(s) that are not on disk: "
        f"{sorted(missing)} — re-run scripts/vendor_fonts.py"
    )


def test_no_font_url_still_points_at_google():
    """The rewrite is the whole point of vendoring. One missed url() would be
    invisible on any machine with internet, which is every machine that would
    review it."""
    css = _font_css()
    for host in ("fonts.gstatic.com", "fonts.googleapis.com"):
        assert host not in css, (
            f"fonts.css still references {host} — the URL rewrite missed something"
        )


def test_the_material_symbols_ligature_rule_survived():
    """Google's own rule, not ours. Without 'liga' the markup
    `<span class="material-symbols-outlined">storefront</span>` renders the word
    even when the font loads perfectly."""
    css = _font_css()
    assert ".material-symbols-outlined" in css, (
        "the .material-symbols-outlined rule is gone — cartflow-ui.css only "
        "overrides font-size and does not define the family or the ligature"
    )
    assert "'liga'" in css, "the 'liga' font-feature-setting is gone — icons will render as words"
    assert "Material Symbols Outlined" in css


def test_all_three_families_are_present():
    """Inter and Fraunces degrade to a system sans and serif, so their absence is
    survivable and easy to miss in review. Asserted anyway — the point is that a
    regenerate which silently dropped a family gets caught here."""
    css = _font_css()
    for family in ("Inter", "Fraunces", "Material Symbols Outlined"):
        assert family in css, f"fonts.css has no @font-face for {family}"


# --- the compiled stylesheet --------------------------------------------

def test_the_compiled_tailwind_stylesheet_exists_and_carries_the_theme():
    """Tailwind is a build artefact now. A missing file is not a degraded page,
    it is an unstyled one, and the custom colour tokens are the part most likely
    to be lost to a config that stopped being read."""
    assert TAILWIND_CSS.exists(), (
        "app/static/css/tailwind.css is missing — run:\n"
        "  npx tailwindcss -i app/static/css/tailwind-input.css "
        "-o app/static/css/tailwind.css --minify"
    )
    css = TAILWIND_CSS.read_text(encoding="utf-8")
    assert len(css) > 10_000, f"tailwind.css is only {len(css)} bytes — build looks truncated"

    # Tokens that exist only because tailwind.config.js was read. A build that
    # silently fell back to stock Tailwind would still be large and still fail here.
    for token in (".text-muted", ".bg-card", ".border-border", ".font-display"):
        assert token in css, (
            f"{token} is absent from the compiled CSS — tailwind.config.js was "
            "probably not picked up by the build"
        )
