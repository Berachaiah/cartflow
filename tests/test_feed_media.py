"""
Multi-photo posts, the double-tap gesture, and the share sheet's brand marks.

Three reports, one card:

1. "when someone wants to post multiple photos, it should be a swiping form, the
   way I'm seeing it in the sample all the photos are showing at once". The feed
   rendered `post.media[:3]` into a `grid grid-cols-3` — every photo visible at
   once, each squashed to a third of the width, and *anything past the third
   silently dropped*. A five-photo post became three thumbnails and two photos
   nobody could ever see. The dropped-photo half is what this file guards hardest,
   because it is invisible: the page looks finished either way.

2. "add the feature for a double tap on the mobile to create a like".

3. "when they share a post, make it show the real app icons, cuz you didn't use
   the real icons for whatsapp, IG, X, facebook". The sheet stood in with
   Material Symbols — `chat`, `photo_camera`, `tag`, `thumb_up` — and the buttons
   toasted "Shared to WhatsApp" without opening anything.

The carousel is CSS scroll-snap, not a JS slider, so most of what makes it work
is class names and a couple of CSS properties. That makes it cheap to break by
tidying a class list, which is why the primitives are asserted individually with
the reason attached to each.
"""

import html
import re
from pathlib import Path

from httpx import AsyncClient

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
HOME = (TEMPLATES / "home.html").read_text(encoding="utf-8")
ICONS = (TEMPLATES / "partials" / "brand_icons.html").read_text(encoding="utf-8")


def _code(src: str) -> str:
    """Source with Jinja and JS block comments removed.

    Needed because the comments here explain what the code replaced — they name
    `dblclick` and quote the old "Shared to WhatsApp" toast — and a plain
    substring search reads those explanations as the very thing they warn about.
    """
    src = re.sub(r"\{#.*?#\}", "", src, flags=re.DOTALL)
    return re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


HOME_CODE = _code(HOME)


def _feed_media_srcs() -> list[str]:
    """Every photo URL in the SEEDED feed, in document order.

    Read from `tests/feed_data.py` rather than scraped out of `home.html`: posts
    are rows now, so the template holds no photo URLs at all and scraping it was
    the only reason this assertion ever passed.
    """
    from tests.feed_data import ALL_FEED_PHOTOS

    srcs = list(ALL_FEED_PHOTOS)
    assert len(srcs) >= 3, f"expected the sample feed to have several photos, found {len(srcs)}"
    return srcs


def _multi_photo_track(page: str) -> str:
    """The attributes of the first .post-track belonging to a multi-photo post.

    Not simply the first .post-track in the document: the sample feed opens with a
    single-photo post, whose track carries none of the carousel affordances by
    design ('1/1' and one dot are noise). Matching the first one made the tests
    assert against the wrong element and report the carousel as broken.
    """
    tracks = re.findall(r'<div class="post-track[^"]*"([^>]*?)>', page, re.DOTALL)
    assert tracks, "no .post-track elements in the rendered feed"
    multi = [t for t in tracks if "carousel" in t]
    assert multi, "no .post-track announces itself as a carousel"
    return multi[0]


# --- 1. no photo is dropped, and they are one at a time -----------------

async def test_every_photo_in_the_feed_reaches_the_page(sample_feed, client: AsyncClient):
    """The `[:3]` slice bug, stated as an invariant rather than a class name.

    This is the assertion that survives a rewrite of the carousel: however the
    markup changes, a photo someone posted has to appear in the response.
    """
    r = await client.get("/")
    assert r.status_code == 200, r.text
    # Compared against the escaped form: these URLs carry query strings, so Jinja's
    # autoescape renders every `&` as `&amp;` in the attribute. Searching for the raw
    # URL reports all of them missing and points the finger at the wrong bug.
    srcs = _feed_media_srcs()
    missing = [s for s in srcs if html.escape(s, quote=False) not in r.text]
    assert not missing, (
        f"{len(missing)} of {len(srcs)} feed photos never render — the media "
        f"list is being sliced again. First missing: {missing[0]}"
    )


def test_the_three_up_grid_is_gone():
    assert "post.media[:3]" not in HOME, (
        "post.media[:3] is back. Anything past the third photo is silently discarded"
    )
    assert "grid grid-cols-3 gap-[2px]" not in HOME, (
        "the 3-up photo grid is back; multiple photos are a carousel, one at a time"
    )


async def test_slides_are_one_per_photo_and_full_width(sample_feed, client: AsyncClient):
    r = await client.get("/")
    track = re.search(r'class="post-track([^"]*)"', r.text)
    assert track, "no .post-track in the rendered feed"
    tokens = track.group(1).split()
    for cls, why in [
        ("flex", "slides need to lay out in a row"),
        ("overflow-x-auto", "without a scroll container there is nothing to swipe"),
        ("snap-x", "no snap axis means the swipe stops between two photos"),
        ("snap-mandatory", "proximity snapping lets a slow drag rest mid-photo"),
        ("hide-scrollbar", "a visible scrollbar under a photo reads as a rendering bug"),
    ]:
        assert cls in tokens, f"post-track lost `{cls}` — {why}"

    slides = re.findall(r'class="snap-center shrink-0 w-full([^"]*)"', r.text)
    assert len(slides) == len(_feed_media_srcs()), (
        f"{len(slides)} slides for {len(_feed_media_srcs())} photos. `w-full` makes one "
        "slide exactly one viewport wide and `shrink-0` stops flex from cramming them "
        "side by side, which is what produced the all-at-once grid look"
    )


def test_swipe_cannot_navigate_the_browser_back():
    assert "overscroll-behavior-x:contain" in HOME, (
        "without overscroll-behavior-x:contain, swiping past the last photo becomes the "
        "browser's back gesture — on iOS that leaves the feed entirely, mid-swipe"
    )
    assert "touch-action:pan-x pan-y" in HOME, (
        "the track needs an explicit touch-action: it must pan horizontally while still "
        "letting a vertical drag scroll the feed underneath"
    )
    assert "touch-action:manipulation" in HOME, (
        ".post-media needs touch-action:manipulation, which excludes double-tap-zoom — "
        "otherwise iOS Safari zooms the page instead of liking the post"
    )


async def test_a_multi_photo_post_says_how_many(sample_feed, client: AsyncClient):
    """The n/N counter and the dots — and only on posts that have more than one."""
    r = await client.get("/")
    counters = re.findall(r'class="post-counter[^"]*"[^>]*>([^<]+)<', r.text)
    assert counters, "no photo counter on a multi-photo post"
    assert counters[0].strip() == "1/3", (
        f"the counter ships as {counters[0]!r}; it must start at the first photo of the "
        "sample's 3-photo post, since JS only rewrites it once you scroll"
    )
    # `post-dot` is a prefix of `post-dots`, the container — count the dots only.
    dots = len(re.findall(r'class="post-dot(?![a-z])', r.text))
    assert dots == 3, f"expected 3 dots for the one multi-photo post, found {dots}"
    # Single-photo posts get no chrome at all.
    assert r.text.count('class="post-counter') == 1, (
        "a counter appeared on a single-photo post; '1/1' is noise on a photo"
    )


async def test_slides_are_reachable_without_a_pointer(sample_feed, client: AsyncClient):
    r = await client.get("/")
    attrs = _multi_photo_track(r.text)
    assert 'tabindex="0"' in attrs, (
        "the scroll container is not focusable, so photos 2..n cannot be reached by "
        "keyboard at all"
    )
    assert 'aria-roledescription="carousel"' in attrs, "the carousel does not announce itself"
    assert r.text.count('aria-roledescription="slide"') == 3, (
        "slides must be individually labelled, or a screen reader reads three unrelated "
        "images with no sense of position"
    )
    # And the affordance is not paid for on posts that don't need it.
    single = [t for t in re.findall(r'<div class="post-track[^"]*"([^>]*?)>', r.text, re.DOTALL)
              if "carousel" not in t]
    assert single and all('tabindex="0"' not in t for t in single), (
        "single-photo posts are taking a tab stop for a carousel they don't have"
    )


# --- 2. double-tap likes, and only likes --------------------------------

def test_double_tap_is_wired_from_pointer_events():
    for token, why in [
        ("pointerdown", "the gesture start"),
        ("pointermove", "needed to tell a tap from a swipe"),
        ("pointerup", "the gesture end"),
        ("pointercancel", "a pan hands the pointer to the scroller and fires no pointerup"),
    ]:
        assert token in HOME_CODE, f"double-tap is missing its {token} handler — {why}"
    assert "dblclick" not in HOME_CODE, (
        "dblclick offers no hook to veto the gesture mid-swipe, which is why this is "
        "counted from pointer events instead"
    )


def test_a_swipe_does_not_like_the_post():
    assert re.search(r"SLOP_PX\s*=\s*(\d+)", HOME_CODE), "the swipe-veto threshold is gone"
    slop = int(re.search(r"SLOP_PX\s*=\s*(\d+)", HOME_CODE).group(1))
    assert 6 <= slop <= 20, (
        f"SLOP_PX is {slop}px. Much smaller and a shaky thumb cancels real double-taps; "
        "much larger and flicking through a carousel likes the post every few photos"
    )
    assert "if (moved" in HOME_CODE, "the `moved` veto is no longer checked on pointerup"


def test_double_tap_never_removes_a_like():
    """IG/TikTok behaviour, and the safer half of it.

    The gesture is easy to fire by accident while swiping, and quietly removing a
    like you already gave is the one outcome you cannot see happen.
    """
    assert "cfLike(btn, true)" in HOME, (
        "the double-tap handler no longer forces `true` — if it toggles, an accidental "
        "double-tap on a post you already liked silently un-likes it"
    )
    # The like is persisted now (`POST /api/posts/{id}/like`), so the single path
    # is cfLike: it paints the card and writes the row. setLiked stays the one
    # place that decides what "liked" looks like.
    assert "function cfLike" in HOME and "function setLiked" in HOME and "function toggleLike" in HOME, (
        "both ways to like a post must go through one path, or the button and the "
        "gesture end up disagreeing about the count"
    )
    assert "/api/posts/" in HOME and "/like" in HOME, (
        "a like that is not sent anywhere is a like that disappears on reload"
    )


async def test_the_burst_heart_cannot_swallow_a_tap(sample_feed, client: AsyncClient):
    r = await client.get("/")
    hearts = r.text.count('class="tap-heart')
    # One per rendered post: the count comes from the seed, not from a literal.
    assert hearts == len(sample_feed), f"expected one .tap-heart per post, found {hearts}"
    heart_css = re.search(r"\.tap-heart\{([^}]*)\}", HOME)
    assert heart_css, "no .tap-heart rule"
    assert "pointer-events:none" in heart_css.group(1), (
        "the heart overlays the middle of the photo; without pointer-events:none it eats "
        "the second half of the very gesture that summoned it"
    )
    assert "prefers-reduced-motion" in HOME, (
        "the burst animation must be suppressed under prefers-reduced-motion — the like "
        "still registers, it just doesn't fly"
    )


async def test_like_state_is_announced(sample_feed, client: AsyncClient):
    r = await client.get("/")
    assert 'aria-pressed="false"' in r.text, (
        "the like button carries no aria-pressed, so a screen reader cannot tell a liked "
        "post from an unliked one"
    )


# --- 3. the share sheet wears the real marks ----------------------------

def test_brand_marks_are_the_real_paths():
    """Real geometry, not a generic glyph that vaguely gestures at the service."""
    for brand in ("whatsapp", "instagram", "x", "facebook"):
        assert f'name == "{brand}"' in ICONS, f"no mark defined for {brand}"
    paths = re.findall(r'<path d="([^"]+)"', ICONS)
    assert len(paths) == 4, f"expected 4 brand paths, found {len(paths)}"
    for p in paths:
        # 150 rather than something larger: X's real mark is two crossing strokes and
        # its official path is only 194 characters. A threshold above that rejects the
        # genuine article for being too simple.
        assert len(p) > 150, (
            f"a brand path is only {len(p)} characters long — that is a placeholder shape, "
            "not a real mark"
        )
    assert "currentColor" in ICONS, "the marks must inherit colour so one copy serves both themes"
    assert "simpleicons.org" in ICONS, (
        "the provenance note is gone. These are CC0 path data from Simple Icons and the "
        "marks remain their owners' trademarks — that needs to stay written down"
    )


def test_the_stand_in_glyphs_are_gone():
    sheet = re.search(r"grid grid-cols-3 gap-4 text-center text-sm(.*?)</div>", HOME, re.DOTALL)
    assert sheet, "could not locate the share sheet grid"
    for glyph in ("photo_camera", "thumb_up", ">tag<", ">chat<"):
        assert glyph not in sheet.group(1), (
            f"{glyph} is back in the share sheet. A camera is not the Instagram mark and a "
            "thumbs-up is not the Facebook one"
        )


async def test_four_brand_tiles_render(client: AsyncClient):
    r = await client.get("/")
    # Counted as class attributes, not as a substring: base.html's inline stylesheet
    # now contains the `.brand-tile` rule itself, which a plain count reads as a
    # fifth tile.
    tiles = re.findall(r'class="[^"]*\bbrand-tile\b[^"]*"', r.text)
    assert len(tiles) == 4, f"expected 4 brand tiles, found {len(tiles)}"
    for label in ("WhatsApp", "Instagram", "Facebook"):
        assert f">{label}</span>" in r.text, f"the {label} button lost its label"


def test_brand_marks_stay_white_in_the_light_theme():
    """The marks are fill="currentColor" on a tile painted the service's colour.

    They were written with Tailwind's `text-white`, and base.html deliberately
    darkens `.text-white` under [data-theme="light"] so ordinary white text stays
    readable on a pale card. That flip painted every mark near-black on its brand
    colour — a dark WhatsApp glyph on green, and a dark X glyph on black, which is
    invisible. `.brand-tile` pins the white in both themes.
    """
    tile = re.search(r'class="([^"]*brand-tile[^"]*)"', ICONS)
    assert tile, "the share tile lost its .brand-tile class"
    assert "text-white" not in tile.group(1).split(), (
        "the tile is using Tailwind's `text-white` again, which base.html darkens "
        "under [data-theme=\"light\"] — in the light theme the mark goes near-black on "
        "the brand colour, and X's mark becomes black-on-black"
    )
    rule = re.search(r"\.brand-tile\{([^}]*)\}", BASE)
    assert rule, ".brand-tile has no CSS rule in base.html, so nothing sets the colour"
    assert "color:#fff" in rule.group(1) and "!important" in rule.group(1), (
        "the .brand-tile rule must force white: it has to beat both Tailwind's "
        "utilities and the light-theme override"
    )


def test_share_buttons_open_real_endpoints():
    """They used to toast 'Shared to WhatsApp' and do nothing at all."""
    for host, why in [
        ("wa.me", "WhatsApp's share intent"),
        ("x.com/intent/post", "X's post intent"),
        ("facebook.com/sharer", "Facebook's sharer"),
    ]:
        assert host in HOME_CODE, f"{why} is missing — that button promises a share it cannot perform"
    assert "Shared to " not in HOME_CODE, (
        "a button is claiming a share happened again. Either open the service or say what "
        "you actually did — a toast is not a share"
    )


def test_opened_tabs_cannot_reach_back():
    opens = re.findall(r"window\.open\([^)]*\)", HOME_CODE)
    assert opens, "no window.open calls found — did the share intents move?"
    for call in opens:
        assert "noopener" in call, (
            f"window.open without noopener: {call}. The opened tab gets a handle on this "
            "one through window.opener and can navigate it"
        )


def test_instagram_and_dm_say_what_they_actually_do():
    """Neither has a web share endpoint, so neither may pretend to have one."""
    assert "Link copied — paste it into your Instagram story or bio" in HOME_CODE, (
        "Instagram publishes no web share URL. Copying the link is the honest fallback; "
        "claiming a share is not"
    )
    assert "Link copied — paste it into a chat" in HOME_CODE, (
        "CartFlow messaging has no compose-with-attachment yet, so the Message button "
        "must copy rather than open a thread that cannot carry the post"
    )