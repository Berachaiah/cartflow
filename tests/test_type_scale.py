"""
Typographic-scale invariants across the templates.

Background: a report that "only notifications, login, signup and messages are
the correct size, the rest are all off". Two separate things were true. One was
a real layout bug in the shell (see test_layout_shell.py). The other was this —
the four pages named as correct are exactly the four that delegate their
headings to the `page_head`/`section_head` macros in partials/ui.html, while
every other page rolled its own. That produced eight slightly different scales,
and worse, headings written as a bare `font-bold` with no size class inherited
16px Inter *sans* where the reference pages render 15px Fraunces *serif*. A
different typeface at a different size in the same visual slot is the kind of
thing you see immediately and cannot name — it reads as "the sizing is off".

So the rule enforced here is not "every heading is 15px". It is: a heading may
not silently inherit its size and face. Either it opts into the display face
with an explicit size, or it is one of the named exceptions below, each of which
is a deliberate different tier.

The expected values are read out of partials/ui.html rather than hardcoded, so
moving the canonical scale updates the test with it instead of against it.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
UI = (TEMPLATES / "partials" / "ui.html").read_text(encoding="utf-8")

# A trailing \b after the bracket form would never match: `]` and the following
# space are both non-word characters, so there is no boundary between them. Keep
# the anchor on the bare-word form only.
_SIZE = re.compile(r"\btext-(?:\[[^\]]+\]|(?:xs|sm|base|lg|xl|[2-9]xl)\b)")
_HEADING = re.compile(r"<h([1-4])\s[^>]*class=\"([^\"]*)\"")

# Classes that set their own size and face in CSS, so a utility would be
# redundant or would fight them. `.auth-title` styles the login/signup family —
# the pages the report named as correct — and `.section-label` is the small
# uppercase group label above a panel, deliberately not a heading tier.
# `.cf-splash-word` is the wordmark on the boot splash: base.html styles it at
# 26px/900 in the display face, over a dark and a light palette. It is a
# component, not a heading tier — the only h1 in the app that is a logo.
SELF_STYLED = ("auth-title", "section-label", "cf-splash-word")


def _canonical_section_classes() -> set[str]:
    """The class list section_head() applies, straight from the macro."""
    macro = re.search(r"{% macro section_head\(.*?{% endmacro %}", UI, re.DOTALL)
    assert macro, "section_head macro not found — partials/ui.html changed shape"
    classes = re.search(r"class=\"(font-display[^\"]*)\"", macro.group(0))
    assert classes, "section_head no longer sets font-display — scale moved"
    return set(classes.group(1).split())


def _headings() -> list[tuple[str, int, str]]:
    out = []
    for template in sorted(TEMPLATES.rglob("*.html")):
        for line_no, line in enumerate(
            template.read_text(encoding="utf-8").splitlines(), 1
        ):
            for _level, classes in _HEADING.findall(line):
                out.append((template.name, line_no, classes))
    return out


def test_the_macro_scale_is_what_we_think_it_is():
    """Everything below is derived from this, so assert it directly rather than
    letting a change to the macro quietly make the other tests vacuous."""
    canonical = _canonical_section_classes()
    assert "font-display" in canonical
    assert any(c.startswith("text-[") for c in canonical), (
        f"section_head has no explicit size: {sorted(canonical)}"
    )
    assert "leading-tight" in canonical


def test_no_heading_inherits_its_size():
    """A heading with no size class renders at the body size in the body face.
    In a slot the eye expects to be a heading that reads as a page whose
    proportions are wrong, which is precisely how this was reported."""
    offenders = [
        f"{name}:{line} class={classes!r}"
        for name, line, classes in _headings()
        if not _SIZE.search(classes)
        and not any(marker in classes for marker in SELF_STYLED)
        and "font-size" not in classes
    ]
    assert not offenders, (
        "headings with no explicit size (they inherit 16px Inter, where the "
        "reference pages render the display face): " + "; ".join(offenders)
    )


def test_display_face_headings_all_use_a_scale_step():
    """`font-display` is the heading voice, so the sizes it appears at are the
    app's heading scale. Keep that a small closed set — a one-off step is how a
    scale turns back into eight scales."""
    allowed = {
        "text-[15px]",  # section heading (the macro's own step)
        "text-[16px]",
        "text-[17px]",
        "text-base",    # override top bars, mobile
        "text-lg",      # page title, and every bottom-sheet title
        "text-xl",
        "text-2xl",     # the wordmark
        "text-3xl",
    }
    seen, offenders = set(), []
    for name, line, classes in _headings():
        if "font-display" not in classes:
            continue
        for size in _SIZE.findall(classes):
            seen.add(size)
            if size not in allowed:
                offenders.append(f"{name}:{line} {size}")
    assert seen, "no font-display headings found at all — the regex is stale"
    assert not offenders, f"heading sizes outside the scale: {'; '.join(offenders)}"


def test_the_reference_pages_still_delegate_to_the_macros():
    """messages/notifications are the baseline the rest was normalised against.
    If they start hand-rolling headings there is no baseline left, and the drift
    this test exists to catch becomes unmeasurable."""
    for page in ("messages.html", "notifications.html"):
        body = (TEMPLATES / page).read_text(encoding="utf-8")
        assert "partials/ui.html" in body, f"{page} stopped importing the macros"
        assert "page_head(" in body or "section_head(" in body, (
            f"{page} no longer calls the heading macros"
        )
