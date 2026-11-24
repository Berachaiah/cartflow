"""Feed ranking, scored by a model that MLflow trained and versioned.

WHY THIS EXISTS. Doc 18 §25 lists "MLFlow recommendation models" as the future of
ranking, and the feed it describes is currently chronological. This module is the
seam: the feed hands it candidate posts, it returns them in model order, and the
model is a JSON artifact that `ml/train_ranker.py` writes and MLflow records.

WHY A JSON FILE AND NOT A PICKLED PIPELINE. Two reasons, both about the host this
runs on. A Vercel function has a 30s ceiling, a read-only filesystem and a cold
start that is charged to the first person who opens the feed — pulling in
`mlflow` + `scikit-learn` + `numpy` (~1 GB unpacked) to multiply nine numbers is
the wrong trade. The artifact here is `{"features": [...], "weights": [...],
"bias": ...}`: the scoring path is `bias + Σ w·x`, pure Python, no import cost,
and it can be loaded from a 1 KB file. MLflow remains the registry and the audit
trail; it is not in the request path.

WHY THE FEATURE LIST LIVES HERE. If training and serving each define their own
feature order, a model silently scores the wrong column and the feed gets worse
in a way no test notices. `FEATURES` is the contract: the trainer imports it, the
artifact records it, and `load_model` refuses an artifact whose feature list does
not match. A rejected model falls back to chronological order, which is a
degraded feed rather than a scrambled one.

WHY EVERY SIGNAL IS NORMALIZED. These are all ratios on 0..1 so a weight means
the same thing across features and a re-train on a bigger catalogue does not have
to relearn a scale. `age_hours_norm` is 0 for a brand-new post and 1 at a week
old, so a negative weight is "fresher ranks higher".
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.core.config import get_settings
from app.models.post import Post
from app.models.user import User

logger = logging.getLogger("cartflow.ranking")

# Bumped only when the artifact's meaning changes; `load_model` treats any other
# value as "this was written by a different CartFlow" and keeps the old order.
MODEL_SCHEMA = 1

# The contract. Order matters: weights are positional.
FEATURES: tuple[str, ...] = (
    "follows_author",        # the viewer follows whoever wrote it (doc 18 §5)
    "same_organization",     # same campus/university as the viewer (§12)
    "author_is_seller",      # a shop posting, rather than a person
    "age_hours_norm",        # freshness, 0 = now, 1 = a week old (§14)
    "like_count_norm",       # engagement (§5), saturating at MAX_LIKES
    "comment_count_norm",    # ditto; 0 today because comments are unbuilt
    "has_media",             # photo posts read as more substantial
    "has_tagged_product",    # shop content that leads somewhere (§20)
    "caption_length_norm",   # very short captions are often low-signal
)

MAX_AGE_HOURS = 168.0   # one week
MAX_LIKES = 100.0
MAX_COMMENTS = 50.0
MAX_CAPTION = 500.0


@dataclass(frozen=True)
class Model:
    """A trained linear ranker plus the provenance needed to explain it."""

    features: tuple[str, ...]
    weights: tuple[float, ...]
    bias: float
    trained_at: str | None = None
    metrics: dict = field(default_factory=dict)
    path: str | None = None

    def score(self, features: dict[str, float]) -> float:
        return self.bias + sum(
            w * features.get(name, 0.0) for name, w in zip(self.features, self.weights)
        )


# path -> (mtime, model). Re-reading a 1 KB file per feed render would be wasteful
# and posting a new model should not need a redeploy, so the file's mtime is the
# cache key: replace the file and the next request sees it.
_CACHE: dict[str, tuple[float, Model | None]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def features_for(
    post: Post,
    author: User,
    viewer: User | None,
    *,
    follows_author: bool = False,
    now: datetime | None = None,
) -> dict[str, float]:
    """The model's input row for one (viewer, post) pair.

    Deliberately built from columns that already exist and are already loaded by
    the feed query — no extra round trip, and no signal invented from a table
    that does not exist yet. Saves/shares/reposts (doc 18 §5) are absent from the
    schema, so they are absent here rather than faked with a constant column that
    would train a weight on nothing.
    """
    moment = now or _utc_now()
    created = _parse(post.created_at.isoformat() if post.created_at else None)
    age_hours = 0.0
    if created is not None:
        age_hours = max(0.0, (moment - created).total_seconds() / 3600.0)

    viewer_org = getattr(viewer, "organization_id", None) if viewer else None
    same_org = bool(viewer_org and author.organization_id == viewer_org)

    caption = post.body or ""
    return {
        "follows_author": 1.0 if follows_author else 0.0,
        "same_organization": 1.0 if same_org else 0.0,
        "author_is_seller": 1.0 if getattr(author, "is_seller", False) else 0.0,
        "age_hours_norm": min(age_hours, MAX_AGE_HOURS) / MAX_AGE_HOURS,
        "like_count_norm": min(float(post.like_count or 0), MAX_LIKES) / MAX_LIKES,
        "comment_count_norm": min(float(post.comment_count or 0), MAX_COMMENTS) / MAX_COMMENTS,
        "has_media": 1.0 if post.images else 0.0,
        "has_tagged_product": 1.0 if post.tagged_product_slugs else 0.0,
        "caption_length_norm": min(len(caption), MAX_CAPTION) / MAX_CAPTION,
    }


def _decode(payload: dict) -> Model:
    """Validate an artifact, or raise. Bad input must never become a live model."""
    if payload.get("schema") != MODEL_SCHEMA:
        raise ValueError(f"artifact schema {payload.get('schema')!r} != {MODEL_SCHEMA}")
    features = tuple(payload.get("features") or ())
    if features != FEATURES:
        raise ValueError("artifact feature list does not match this build")
    weights = tuple(float(w) for w in payload.get("weights") or ())
    if len(weights) != len(features):
        raise ValueError("weights and features have different lengths")
    return Model(
        features=features,
        weights=weights,
        bias=float(payload.get("bias", 0.0)),
        trained_at=payload.get("trained_at"),
        metrics=dict(payload.get("metrics") or {}),
        path=payload.get("origin"),
    )


def load_model(path: str | Path | None = None) -> Model | None:
    """The active model, or None when there isn't a usable one.

    None is a normal answer, not an error: the feed must render on a fresh clone,
    on a deploy where training has not run yet, and on a host whose model file was
    replaced by something invalid. All three keep chronological order.
    """
    settings = get_settings()
    if not getattr(settings, "RANKING_ENABLED", True):
        return None

    target = Path(path or settings.RANKING_MODEL_PATH)
    key = str(target)
    try:
        mtime = target.stat().st_mtime
    except OSError:
        _CACHE.pop(key, None)
        return None

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        model: Model | None = _decode(payload)
        logger.info(
            "ranking model loaded (trained %s, artifact %s)",
            model.trained_at,
            model.path,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # A malformed artifact is an operational mistake; say so once per file
        # version and keep serving the feed in date order.
        logger.warning("ignoring unusable ranking model at %s: %s", target, exc)
        model = None

    _CACHE[key] = (mtime, model)
    return model


def rank(
    rows: Sequence[tuple[Post, User]],
    *,
    viewer: User | None,
    followed_author_ids: set[uuid.UUID],
    model: Model | None = None,
    now: datetime | None = None,
) -> list[tuple[Post, User]]:
    """Order `rows` by model score, newest first where scores tie.

    Ties fall back to `created_at` rather than to dict order so the result is
    deterministic and a model with all-zero weights reproduces the chronological
    feed exactly — which is what makes the fallback path testable and what makes
    a half-trained model harmless.
    """
    active = model if model is not None else load_model()
    if active is None or not rows:
        return list(rows)

    moment = now or _utc_now()
    scored = []
    for post, author in rows:
        feats = features_for(
            post,
            author,
            viewer,
            follows_author=author.id in followed_author_ids,
            now=moment,
        )
        scored.append((active.score(feats), post.created_at, post, author))

    # `-timestamp` is not sortable across None and datetime, so compare through
    # the epoch float; a missing created_at sorts last rather than raising.
    def _sort_key(item):
        score, created, _, _ = item
        stamp = created.timestamp() if created else 0.0
        return (-score, -stamp)

    scored.sort(key=_sort_key)
    return [(post, author) for _, _, post, author in scored]


__all__ = [
    "FEATURES",
    "MODEL_SCHEMA",
    "Model",
    "features_for",
    "load_model",
    "rank",
]
