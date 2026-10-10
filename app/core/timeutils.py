"""
UTC datetime helpers.

Exists for one reason: SQLite has no native timestamp type, so a column
declared `DateTime(timezone=True)` round-trips as a *naive* datetime
there, while Postgres returns an aware one. Any code that subtracts a
stored timestamp from `datetime.now(timezone.utc)` therefore works in
production and raises `TypeError: can't subtract offset-naive and
offset-aware datetimes` under SQLite (tests, and the dev preview DB).

Normalizing at the point of comparison is the fix. Assuming UTC for a
naive value is correct here because every timestamp this app writes is
UTC — there is no local-time path that could make the assumption wrong.

The two formatters at the bottom are the display side of the same
problem: a stored timestamp has to become "2h" in a notification row, and
doing that inline in a template means re-solving the naive/aware question
at every call site.
"""

from datetime import datetime, timezone


def ensure_utc(value: datetime) -> datetime:
    """Return `value` as a timezone-aware UTC datetime.

    Naive input is *interpreted* as UTC, not converted. Aware input is
    converted, so a value from a differently-offset source still compares
    correctly.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    """Aware UTC now. A named helper so call sites can't drift into
    `datetime.utcnow()`, which returns a naive value and reintroduces
    exactly the bug this module exists to prevent."""
    return datetime.now(timezone.utc)


# --- display -------------------------------------------------------------


def time_ago(value: datetime | None, *, now: datetime | None = None) -> str:
    """A timestamp as a compact age: "now", "5m", "2h", "3d", "2w", then a date.

    Compact rather than "2 hours ago" because every place this appears is a
    dense row where the age is the *last* column — the activity inbox, an inbox
    conversation, a feed post header. The curated feed in home.html already
    prints "2h" / "1d" / "30m" as literals, so a real timestamp rendered beside
    a placeholder one has to read the same way; anything else looks like two
    different apps' data in one list.

    Past 5 weeks it switches to an absolute date, because "9w" is a number
    nobody converts. The year is only added when it isn't the current one, so
    the common case stays two words wide.

    A timestamp slightly in the FUTURE returns "now" rather than a negative
    age. That is clock skew between the app server and the database, not a
    time traveller, and "in -3m" is a worse answer than rounding to zero.

    `now` is injectable so tests can pin the boundaries instead of sleeping.
    Returns "" for None, so a template can render it unconditionally.
    """
    if value is None:
        return ""

    moment = ensure_utc(value)
    reference = ensure_utc(now) if now is not None else utc_now()
    seconds = (reference - moment).total_seconds()

    if seconds < 45:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    if seconds < 604800:
        return f"{int(seconds // 86400)}d"
    if seconds < 3024000:  # 5 weeks
        return f"{int(seconds // 604800)}w"

    # `%-d` is not portable (glibc/BSD only), so the day is interpolated.
    if moment.year == reference.year:
        return f"{moment.day} {moment:%b}"
    return f"{moment.day} {moment:%b} {moment.year}"


def absolute_time(value: datetime | None) -> str:
    """The full timestamp, for the `title` tooltip beside a `time_ago` label.

    "2w" is honest but imprecise, and the exact moment is occasionally what
    someone actually wants (when did that person follow me?). UTC is stated
    rather than silently converted: the app has no per-user timezone, so
    presenting a UTC instant as local time would be a guess.
    """
    if value is None:
        return ""
    return f"{ensure_utc(value):%d %b %Y, %H:%M} UTC"

