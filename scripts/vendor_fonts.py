#!/usr/bin/env python3
"""Vendor the Google Fonts stylesheets and their font files into app/static.

WHY THIS EXISTS
    Every font in CartFlow is fetched from fonts.googleapis.com at page load, so
    a browser that cannot reach Google gets no typeface and — worse — no icons.
    Material Symbols renders through ligatures: the markup says
    `<span class="material-symbols-outlined">storefront</span>`, and it is the
    font that turns the word into a picture. With the font missing, the user
    reads the literal word "storefront" in the navigation. That is the failure
    this script removes.

    Tailwind was vendored first (tailwind.config.js). This is the other half.

WHAT IT DOES
    Fetches the two stylesheet URLs currently in base.html, downloads every font
    file they reference into app/static/fonts/, and writes app/static/css/fonts.css
    with the URLs rewritten to local paths. Everything else in Google's CSS is
    preserved byte for byte — including the `.material-symbols-outlined` rule
    itself, which is defined by Google and NOT by cartflow-ui.css (that file only
    overrides font-size). Dropping it would leave the ligature settings unset.

    A modern Chrome User-Agent is sent deliberately. Google serves a different
    stylesheet per UA, and the modern one is what yields woff2 plus the
    unicode-range subsetting that keeps the download small. urllib's default UA
    gets TTF, which is several times larger and loses the subsetting.

WHY IT IS A SCRIPT AND NOT A ONE-OFF
    Re-run it whenever the font URLs in base.html change. It is idempotent:
    existing files are skipped unless --force.

USAGE
    ./venv/bin/python scripts/vendor_fonts.py
    ./venv/bin/python scripts/vendor_fonts.py --force     # re-download everything

    Then point base.html at css/fonts.css instead of the two Google <link> tags.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "app" / "static" / "fonts"
CSS_OUT = ROOT / "app" / "static" / "css" / "fonts.css"

# The two <link> hrefs in base.html, verbatim. Keep them in step with it.
SHEETS = {
    "text": (
        "https://fonts.googleapis.com/css2"
        "?family=Inter:wght@300;400;500;600;700;800"
        "&family=Fraunces:opsz,wght@9..144,600;9..144,700;9..144,800"
        "&display=swap"
    ),
    "icons": (
        "https://fonts.googleapis.com/css2"
        "?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1"
        "&display=swap"
    ),
}

# Without this Google serves TTF rather than woff2. See the module docstring.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def local_name(url: str) -> str:
    """A stable, collision-free filename for a Google font URL.

    Google's paths look like /s/inter/v20/UcC73Fwr...woff2 — the basename alone
    is unique in practice, but the family segment is prepended so the directory
    is readable by a human deciding whether a file is still needed.
    """
    parts = [p for p in url.split("/") if p]
    stem = parts[-1]
    family = parts[-3] if len(parts) >= 3 else "font"
    return f"{family}-{stem}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force", action="store_true", help="re-download files that already exist"
    )
    args = ap.parse_args()

    FONT_DIR.mkdir(parents=True, exist_ok=True)

    chunks: list[str] = [
        "/* Vendored from Google Fonts by scripts/vendor_fonts.py — do not edit.",
        " *",
        " * Regenerate rather than patching. The `.material-symbols-outlined`",
        " * rule below is Google's, and it is what makes the ligature markup",
        " * (`<span ...>storefront</span>`) render as an icon instead of the",
        " * literal word. cartflow-ui.css only overrides font-size.",
        " */",
        "",
    ]

    total_bytes = 0
    downloaded = 0
    skipped = 0

    for label, url in SHEETS.items():
        print(f"[{label}] fetching stylesheet")
        try:
            css = fetch(url).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — surface the real reason
            print(f"  FAILED: {exc}", file=sys.stderr)
            return 1

        font_urls = sorted(set(re.findall(r"url\((https://[^)]+)\)", css)))
        print(f"  {len(font_urls)} font file(s) referenced")

        for furl in font_urls:
            name = local_name(furl)
            dest = FONT_DIR / name
            if dest.exists() and not args.force:
                skipped += 1
            else:
                try:
                    blob = fetch(furl)
                except Exception as exc:  # noqa: BLE001
                    print(f"  FAILED {name}: {exc}", file=sys.stderr)
                    return 1
                dest.write_bytes(blob)
                downloaded += 1
                print(f"  + {name}  ({len(blob) / 1024:.0f} KB)")
            total_bytes += dest.stat().st_size
            # Rewrite to a root-relative path. Not url_for: this file is static
            # CSS, served as-is, and never passes through Jinja.
            css = css.replace(furl, f"/static/fonts/{name}")

        chunks.append(f"/* --- {label} --- */")
        chunks.append(css.strip())
        chunks.append("")

    CSS_OUT.write_text("\n".join(chunks))

    print()
    print(f"wrote {CSS_OUT.relative_to(ROOT)}")
    print(f"  {downloaded} downloaded, {skipped} already present")
    print(f"  {total_bytes / 1024 / 1024:.1f} MB of fonts in app/static/fonts/")
    print()
    print("Next: replace the two fonts.googleapis.com <link> tags in base.html")
    print("with a single link to css/fonts.css.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
