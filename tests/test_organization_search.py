"""
Pure-logic unit tests for the organization fuzzy matcher.

These need NO database — they exercise the module-level helpers and the
`_match` method against in-memory `Organization` instances. The divergent-
suffix guard (FUTA vs FUTO) is the subtle, correctness-critical piece; it
gets the most coverage here.
"""

import uuid

from app.models.organization import Organization
from app.repositories.organization import (
    FUZZY_CUTOFF,
    TAIL_CUTOFF,
    OrganizationRepository,
    _normalize,
    _similar,
    _slugify,
    _tail,
)


def _org(official_name: str, short_name: str | None = None) -> Organization:
    return Organization(
        id=uuid.uuid4(),
        official_name=official_name,
        short_name=short_name,
        slug=_slugify(official_name),
        country="Nigeria",
        status="active",
    )


# --- _normalize ---------------------------------------------------------

def test_normalize_lowercases_and_strips_punctuation():
    assert _normalize("University of Lagos!") == "university of lagos"


def test_normalize_expands_univ_abbreviation():
    assert _normalize("Univ. of Lagos") == "university of lagos"
    assert _normalize("Uni of Lagos") == "university of lagos"


def test_normalize_expands_tech_and_sci_and_ampersand():
    assert _normalize("Fed. Uni of Tech") == "fed university of technology"
    assert _normalize("School of Sc") == "school of science"
    assert _normalize("Arts & Science") == "arts and science"


def test_normalize_collapses_whitespace_and_symbols():
    assert _normalize("  A.B.U   Zaria  ") == "a b u zaria"


# --- _tail --------------------------------------------------------------

def test_tail_returns_last_two_words():
    assert _tail("federal university of technology akure") == "technology akure"


def test_tail_short_name_returned_whole():
    assert _tail("unilag") == "unilag"


# --- _match: exact ------------------------------------------------------

class _Repo(OrganizationRepository):
    """Instantiate without a DB — we only call the pure `_match` method."""

    def __init__(self):
        pass  # no super().__init__ — no session needed for _match


def test_match_exact_official_name():
    repo = _Repo()
    existing = [_org("University of Lagos", "UNILAG")]
    assert repo._match("University of Lagos", existing) is existing[0]


def test_match_exact_via_short_name():
    repo = _Repo()
    existing = [_org("University of Lagos", "UNILAG")]
    # Typing the abbreviation resolves to the same row (short_name match).
    assert repo._match("unilag", existing) is existing[0]


def test_match_abbreviated_input_matches_full_name():
    repo = _Repo()
    existing = [_org("University of Lagos", "UNILAG")]
    # "Univ of Lagos" normalizes to "university of lagos" == official_name.
    assert repo._match("Univ of Lagos", existing) is existing[0]


# --- _match: the FUTA vs FUTO divergent-suffix guard --------------------

def test_futa_does_not_match_futo():
    """The load-bearing test: two real, distinct universities sharing a long
    common prefix must NOT be merged. Typing FUTO must never resolve to FUTA."""
    repo = _Repo()
    existing = [_org("Federal University of Technology, Akure", "FUTA")]
    # A brand-new FUTO should find NO match (so it gets created separately).
    match = repo._match("Federal University of Technology, Owerri", existing)
    assert match is None


def test_futo_matches_itself_when_present():
    repo = _Repo()
    existing = [
        _org("Federal University of Technology, Akure", "FUTA"),
        _org("Federal University of Technology, Owerri", "FUTO"),
    ]
    match = repo._match("Federal University of Technology, Owerri", existing)
    assert match is not None
    assert match.short_name == "FUTO"


def test_minor_typo_still_matches():
    """The guard must not be so strict it rejects genuine near-duplicates:
    a small typo in the same institution should still resolve."""
    repo = _Repo()
    existing = [_org("University of Ibadan", "UI")]
    match = repo._match("University of Ibadann", existing)  # doubled trailing n
    assert match is not None
    assert match.short_name == "UI"


def test_unrelated_name_returns_none():
    repo = _Repo()
    existing = [_org("University of Lagos", "UNILAG")]
    assert repo._match("Covenant University", existing) is None


# --- guard-rail sanity on the tuned constants ---------------------------

def test_cutoffs_are_in_sane_range():
    assert 0.5 < FUZZY_CUTOFF < 1.0
    assert 0.5 < TAIL_CUTOFF < 1.0


def test_similar_is_symmetric_and_bounded():
    assert _similar("abc", "abc") == 1.0
    assert 0.0 <= _similar("abc", "xyz") <= 1.0
