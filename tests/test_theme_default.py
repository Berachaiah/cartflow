"""
Theme defaults and the single point of control.

Three separate requirements are locked in here, and each one broke in a way that
was invisible in a screenshot:

1. THE THEME IS RESOLVED BEFORE THE FIRST PAINT. The light palette is
   expressed as `[data-theme="light"]` overrides on top of a dark `:root`, so
   "which palette" is not a CSS change — it means the attribute has to be on
   <html> before the first paint. The theme script used to live at the end of
   <body>, which runs after the document has painted: every single load showed
   a frame of the dark palette and then snapped to light.

   The shipped default is the SYSTEM preference, not a hard-coded light: an
   installed app that ignores the phone's own appearance setting looks broken
   beside every other app on it. On a phone that is not in dark mode that still
   resolves to the light palette, which is what the theme-color meta carries.

2. AN ABSENT KEY MEANS "HASN'T CHOSEN". applyTheme() used to call
   localStorage.setItem unconditionally, so merely rendering a page wrote the
   key from the fallback value. That makes "hasn't chosen" indistinguishable
   from "chose light" after one visit — the default could never change again for
   anyone who had loaded the app, and following the OS would be impossible.
   Only cfSetTheme() may write.

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


def test_absent_or_junk_key_resolves_to_the_system_preference():
    """An unset key follows the device; a junk key must not decide anything.

    The app has three preferences (system / light / dark) and `system` is what
    an absent key means — this test used to demand that only the literal 'dark'
    opted out of light, which was true of the two-state version and is false of
    the three-state one. What still has to hold: no stored value can put a
    palette on <html> that the user did not ask for, and a load with storage
    disabled still pins a theme rather than rendering the bare :root.
    """
    head = _head()
    assert re.search(r"localStorage\.getItem\(\s*['\"]" + STORAGE_KEY + r"['\"]\s*\)", head), (
        "the head bootstrap no longer reads the stored preference, so the first "
        "paint cannot know which theme to use"
    )
    # Exactly three values are accepted; anything else resolves to 'system'.
    assert "['light', 'dark', 'system']" in BASE, "the preference list is no longer the documented three"
    assert re.search(r"indexOf\(stored\)\s*!==\s*-1\s*\?\s*stored\s*:\s*'system'", BASE), (
        "a junk or absent key no longer falls back to 'system' — it must not fall back "
        "to a specific palette, because 'hasn't chosen' and 'chose light' are different"
    )
    # Dark is opt-in twice over: an explicit 'dark', or 'system' on a dark OS.
    assert "cfPref === 'dark'" in head, "an explicit dark preference is no longer honoured in <head>"
    assert "prefers-color-scheme: dark" in head, (
        "the head bootstrap no longer consults the OS, so 'system' cannot resolve before paint"
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


def test_cf_set_theme_is_the_only_writer():
    """One writer app-wide, and the binary flip goes through it.

    This used to assert that toggleTheme() held the setItem call. The rule is
    the same one — a single place may persist a preference — but the writer is
    now cfSetTheme(), which also validates the value against the three
    preferences. A toggleTheme() that wrote storage itself would be a second
    path that could leave something cfSetTheme() would have rejected.
    """
    assert "setItem" in _fn_body("cfSetTheme"), (
        "cfSetTheme() no longer persists, so the choice is lost on navigation"
    )
    assert "cfSetTheme(" in _fn_body("toggleTheme"), (
        "toggleTheme() stopped delegating to cfSetTheme(), so a flip would bypass the "
        "validation and the switch sync"
    )
    # The write goes through the shared constant rather than repeating the
    # literal, so a rename cannot leave the writer pointing at a key the reader
    # never looks up. Count both spellings: a second writer that used the
    # literal would be exactly the drift this test exists to catch.
    assert f"const CF_THEME_KEY = '{STORAGE_KEY}'" in BASE, (
        "CF_THEME_KEY no longer holds the key the head bootstrap reads, so the reader "
        "and the writer can disagree about where the preference lives"
    )
    writers = re.findall(
        r"setItem\(\s*(?:['\"]" + STORAGE_KEY + r"['\"]|CF_THEME_KEY)", BASE
    )
    assert len(writers) == 1, (
        f"{len(writers)} places write the theme key in base.html; there must be exactly "
        "one (cfSetTheme) or the 'hasn't chosen' state leaks away again"
    )


def test_the_theme_control_is_one_shared_switch():
    """Settings and the auth screens render the same partial; the state stays global.

    Settings used to render its own `toggleTheme()` button, which is why this
    test looked for that call. A three-way preference cannot be a binary toggle,
    so the row now renders `partials/theme_switch.html` — the same control the
    auth screens show. What has to stay true is that the partial carries no
    script of its own and the state and click handling remain top-level in
    base.html, or the switch would render as three dead buttons on any page.
    """
    settings = (TEMPLATES / "settings.html").read_text(encoding="utf-8")
    switch = (TEMPLATES / "partials" / "theme_switch.html").read_text(encoding="utf-8")
    assert "partials/theme_switch.html" in settings, "settings.html stopped importing the switch"
    assert "theme_switch()" in settings, "settings.html stopped rendering the Appearance control"
    for pref in ('"system"', '"light"', '"dark"'):
        assert f"data-cf-theme={pref}" in switch, f"the switch lost its {pref} segment"
    assert "<script" not in switch, (
        "the switch partial grew its own script; it must stay state-free or two copies on "
        "one page would fight over the click"
    )
    assert re.search(r"^\s*function cfSetTheme\(", BASE, re.MULTILINE), (
        "cfSetTheme is no longer a top-level function declaration, so the global the "
        "switch depends on may not exist"
    )
    assert re.search(r"^\s*function toggleTheme\(", BASE, re.MULTILINE), (
        "toggleTheme is no longer top-level; keeping the binary flip global is what lets a "
        "future keyboard shortcut or control reuse it"
    )
    assert "[data-cf-theme]" in BASE, "base.html lost the delegated listener for the switch"


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
