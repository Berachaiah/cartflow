"""
Layout-shell invariants: the handful of rules that decide whether a page is the
width of the phone or wider than it.

These exist because of a bug that presented as "the sizing is off on every page
except the simple ones". Nothing was wrong with any page's own markup. #appContent
is a flex row, so <main> is a flex item, and a flex item's default
`min-width:auto` resolves to its min-content width — so main could not shrink
below the widest un-shrinkable thing anywhere inside it. On a page made of
wrapping text that width is small and everything looked fine; on a page with a
dense row it exceeded the viewport, and since the sticky top bar is a child of
main it was laid out at the inflated width too and its buttons sat off-screen.
The content decided whether the shell's bug fired, which is why it looked like
eight separate page bugs instead of one shell bug.

The assertions deliberately derive the expected values from base.html itself
rather than hardcoding them, so changing the shell's padding makes the test
tell you which full-bleed rows now need changing too.
"""

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")

# Pages that render the full shell (not the `bare` auth layout).
PAGES = ["/", "/orders"]

_MAIN_TAG = re.compile(r"<main class=\"([^\"]*)\"")


# --- the flex item that holds every page ---------------------------------

@pytest.mark.parametrize("path", PAGES)
async def test_main_can_shrink_below_its_content(client: AsyncClient, path: str):
    """<main> must carry min-w-0 for as long as it is a flex item.

    Without it a single wide descendant silently widens the whole shell, and the
    symptom appears on the pages that happen to contain one rather than on the
    shell — which is what made the original bug so hard to place.
    """
    r = await client.get(path)
    assert r.status_code == 200, r.text
    classes = _MAIN_TAG.search(r.text)
    assert classes, "no <main class=...> in the response — selector is stale"
    tokens = classes.group(1).split()
    assert "flex-1" in tokens, "main stopped being a flex item; this test needs rethinking"
    assert "min-w-0" in tokens, (
        "main is a flex item without min-w-0, so min-width:auto pins it to its "
        "min-content width and any wide descendant inflates the whole page"
    )


# --- the horizontal-overflow guard sits on the root, not on body ---------

def test_overflow_guard_is_not_on_body():
    """`overflow-x` on body forces the other axis's `visible` to compute to
    `auto`, making body a scroll container that — having auto height — can never
    scroll. Every position:sticky inside it then resolves against a scrollport
    that never moves, so the sticky top bars stop sticking."""
    body_rule = re.search(r"\nbody\{(.*?)\n\}", BASE, re.DOTALL)
    assert body_rule, "body{} rule not found — selector is stale"
    assert "overflow-x" not in body_rule.group(1), (
        "overflow-x is back on body; it belongs on html, or sticky breaks"
    )


def test_overflow_guard_is_on_the_root_with_a_fallback():
    html_rule = re.search(r"\nhtml\{(.*?)\n\}", BASE, re.DOTALL)
    assert html_rule, "html{} rule not found — selector is stale"
    decls = html_rule.group(1)
    # `clip` is the one that keeps sticky working; `hidden` first so engines
    # without `clip` still get a guard. Both, in that order.
    assert "overflow-x:clip" in decls.replace(" ", ""), "root is missing overflow-x:clip"
    assert decls.index("hidden") < decls.index("clip"), (
        "the hidden fallback must come before clip or it overrides it"
    )


# --- full-bleed rows land exactly on the viewport edge -------------------

def _shell_padding() -> tuple[str, str]:
    """The horizontal padding of base.html's content <section>, which is what
    every full-bleed row has to cancel to reach the viewport edge."""
    m = re.search(r"px-([0-9.]+) sm:px-([0-9.]+) py-", BASE)
    assert m, "could not read the shell's horizontal padding from base.html"
    return m.group(1), m.group(2)


def test_full_bleed_negative_margins_match_the_shell_padding():
    """A `-mx-N` row is trying to reach the viewport edge by cancelling the
    shell's padding. If N is not exactly that padding the row overshoots the
    viewport (or stops short of it), and an overshoot is unreachable content
    rather than a visible mistake — the worst kind.
    """
    mobile, sm = _shell_padding()
    allowed = {("", mobile), ("sm:", sm)}

    offenders = []
    found = 0
    for template in sorted(TEMPLATES.rglob("*.html")):
        for line_no, line in enumerate(template.read_text(encoding="utf-8").splitlines(), 1):
            for prefix, value in re.findall(r"(?:^|\s)((?:sm|md|lg|xl):)?-mx-([0-9.]+)", line):
                found += 1
                if (prefix, value) not in allowed:
                    offenders.append(f"{template.name}:{line_no} {prefix}-mx-{value}")

    # Without this the test passes when the regex stops matching anything, which
    # is the same shape of silent-pass the CSP tests were written to avoid.
    assert found, "no -mx- rows matched at all — the regex is stale, not the app"
    assert not offenders, (
        f"full-bleed rows that do not match the shell's px-{mobile} sm:px-{sm}: "
        + ", ".join(offenders)
    )
