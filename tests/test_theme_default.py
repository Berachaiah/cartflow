"""
Theme defaults and the single point of control.

Three separate requirements are locked in here, and each one broke in a way that
was invisible in a screenshot:

1. LIGHT IS THE DEFAULT, AND IT MUST NOT FLASH. The light palette is expressed
   as `[data-theme="light"]` overrides on top of a dark `:root`, so "default to
   light" is not a CSS change — it means the attribute has to be on <html>
   before the first paint. The theme script used to live at the end of <body>,
   which runs after the document has painted: every single load showed a frame
   of the dark palette and then snapped to light.

2. AN ABSENT KEY MEANS "HASN'T CHOSEN". applyTheme() used to call
   localStorage.setItem unconditionally, so merely rendering a page wrote the
   key from the fallback value. That makes "hasn't chosen" indistinguishable
   from "chose light" after one visit — the default could never be changed again
   for anyone who had already loaded the app, and honouring prefers-color-scheme
   later becomes impossible to add. Only toggleTheme() may write.

3. ONE CONTROL, IN SETTINGS. The toggle used to sit in the sidebar, the mobile
   top bar, the bare footer, home.html and shop.html — five copies of a
   preference almost nobody changes twice, each taking space from navigation on
   the screen where space is tightest.

The tests read base.html's source rather than a rendered page for 1-3, because
what matters is *where in the document* the code sits, and an assertion about
document order is exactly what a rendered-DOM check cannot make.
"""

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")

STORAGE_KEY = "cartflow-theme"

# The real <body> tag, anchored to the start of a line. An unanchored `<body`
# also matches the phrase "at the end of <body>" inside base.html's own
# explanatory comment, which sits *above* the head script — so the naive search
# reports the bootstrap as being outside <head> when it is not.
_BODY_TAG = re.compile(r"^<body\b", re.MULTILINE)


def _head() -> str:
    """Everything before the <body> tag."""
    m = _BODY_TAG.search(BASE)
    assert m, "no <body> tag at the start of a line in base.html — selector is stale"
    return BASE[: m.start()]


# --- 1. the theme is resolved before the first paint ---------------------

def test_theme_is_resolved_in_head_before_first_paint():
    head = _head()
    assert STORAGE_KEY in head, (
        f"the {STORAGE_KEY!r} lookup is not in <head>. Light is the default and the "
        "light palette is a [data-theme] override on a dark :root, so resolving the "
        "theme after <body> means every page load flashes dark and then snaps to light"
    )


def test_theme_bootstrap_is_blocking():
    """No async/defer on the bootstrap: deferred means after paint, i.e. a flash."""
    head = _head()
    script = re.search(r"<script\b([^>]*)>(?:(?!</script>).)*?" + STORAGE_KEY, head, re.DOTALL)
    assert script, "could not locate the bootstrap <script> tag in <head>"
    attrs = script.group(1)
    assert "defer" not in attrs and "async" not in attrs and "src=" not in attrs, (
        f"the theme bootstrap must be a blocking inline script; got <script{attrs}>. "
        "defer/async/src all run it after the first paint, which is the flash this fixes"
    )


def test_absent_key_resolves_to_light():
    """Only the 'dark' string opts out of light — anything else falls through."""
    head = _head()
    assert re.search(
        r"getItem\(\s*['\"]" + STORAGE_KEY + r"['\"]\s*\)\s*===\s*['\"]dark['\"]", head
    ), (
        "the bootstrap no longer tests for the 'dark' value specifically. It must, "
        "because every other state — absent key, junk value, storage disabled — has to "
        "resolve to the light default"
    )
    assert head.count("setAttribute('data-theme', 'light')") >= 2, (
        "the catch branch is missing its data-theme fallback: with storage disabled "
        "(private mode, blocked cookies) the app would render the dark palette"
    )


# --- 2. rendering a page must not persist a preference ------------------

def _fn_body(name: str) -> str:
    """Source of a top-level `function name(...)`, by brace matching."""
    start = BASE.index(f"function {name}(")
    depth, i = 0, BASE.index("{", start)
    opened = False
    while i < len(BASE):
        if BASE[i] == "{":
            depth += 1
            opened = True
        elif BASE[i] == "}":
            depth -= 1
            if opened and depth == 0:
                return BASE[start : i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces reading function {name}")


def test_apply_theme_does_not_write_to_storage():
    body = _fn_body("applyTheme")
    assert "setItem" not in body, (
        "applyTheme() writes to localStorage. It must not: applyTheme runs on every "
        "page render, so it would persist the *fallback* and make 'hasn't chosen' "
        "indistinguishable from 'chose light' after a single visit"
    )


def test_toggle_theme_is_the_only_writer():
    assert "setItem" in _fn_body("toggleTheme"), (
        "toggleTheme() no longer persists, so the choice is lost on navigation"
    )
    # One writer, app-wide.
    writers = re.findall(r"setItem\(\s*['\"]" + STORAGE_KEY + r"['\"]", BASE)
    assert len(writers) == 1, (
        f"{len(writers)} places write the theme key in base.html; there must be exactly "
        "one (toggleTheme) or the 'hasn't chosen' state leaks away again"
    )


def test_toggle_theme_stays_global():
    """settings.html's Appearance row is the only caller — and it calls it by name.

    Wrapping this in an IIFE or renaming it breaks that page's single theme
    control silently: nothing else in the app references it, so no other test
    or page would fail.
    """
    settings = (TEMPLATES / "settings.html").read_text(encoding="utf-8")
    assert "toggleTheme()" in settings, "settings.html stopped calling toggleTheme()"
    assert re.search(r"^\s*function toggleTheme\(", BASE, re.MULTILINE), (
        "toggleTheme is no longer a top-level function declaration, so the global "
        "settings.html depends on may not exist"
    )


# --- 3. one theme control, and it lives in Settings ---------------------

def _strip_comments(src: str) -> str:
    """Jinja and JS block comments out, so prose about toggleTheme is not a call.

    base.html mentions toggleTheme() three times in comments explaining why it is
    global and why it is the only writer — exactly the notes a future reader needs,
    and exactly what a naive substring count reads as five theme toggles.
    """
    src = re.sub(r"\{#.*?#\}", "", src, flags=re.DOTALL)
    return re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


def test_settings_is_the_only_theme_control():
    offenders = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        if path.name == "settings.html":
            continue
        src = _strip_comments(path.read_text(encoding="utf-8"))
        # base.html declares the function; declaring is not offering a control.
        calls = len(re.findall(r"(?<!function )\btoggleTheme\s*\(", src))
        if calls > 0:
            offenders[path.name] = calls
    assert not offenders, (
        f"theme toggles outside Settings: {offenders}. A display preference belongs in "
        "Settings → Appearance; copies in the sidebar, the mobile top bar and the footer "
        "spent scarce navigation space on something people set once"
    )


def test_no_stale_toggle_element_ids():
    """The four deleted buttons, by id. Leftover ids mean leftover buttons."""
    for stale in ("themeToggle", "themeToggleMobile", "themeToggleBare"):
        found = [p.name for p in TEMPLATES.rglob("*.html") if f'id="{stale}"' in p.read_text(encoding="utf-8")]
        assert not found, f'id="{stale}" still present in {found}'


# --- the browser chrome follows the app, not the OS ---------------------

def test_one_theme_color_meta_holding_the_light_value():
    metas = re.findall(r"<meta name=\"theme-color\"[^>]*>", BASE)
    assert len(metas) == 1, (
        f"expected exactly one theme-color meta, found {len(metas)}. The old "
        "prefers-color-scheme pair followed the OS, so a dark-mode phone drew dark "
        "browser chrome above a light-rendered app: {metas}"
    )
    assert "prefers-color-scheme" not in metas[0], "theme-color is keyed to the OS again"
    assert 'id="themeColorMeta"' in metas[0], (
        "the meta needs its id — both the head bootstrap and applyTheme() update it by id"
    )
    assert "#F5F3EF" in metas[0], (
        "the shipped theme-color is not the light value, but light is what renders by default"
    )


def test_apply_theme_keeps_the_chrome_in_step():
    assert "themeColorMeta" in _fn_body("applyTheme"), (
        "applyTheme() no longer updates theme-color, so toggling the theme leaves the "
        "status bar on the old palette until the next navigation"
    )


# --- and the page still renders ----------------------------------------

@pytest.mark.parametrize("path", ["/", "/discover", "/marketplace", "/settings"])
async def test_pages_render_without_a_theme_toggle(client: AsyncClient, path: str):
    r = await client.get(path, follow_redirects=True)
    assert r.status_code == 200, r.text
    for stale in ('id="themeToggle"', 'id="themeToggleMobile"', 'id="themeToggleBare"'):
        assert stale not in r.text, f"{stale} rendered on {path}"
