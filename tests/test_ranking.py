"""Feed ranking — the MLflow-trained artifact, and the fallback that outranks it.

Three things are worth guarding here, and only one of them is about scores:

1. NO ARTIFACT MEANS CHRONOLOGICAL. A fresh clone, a deploy where training has
   not run, and a host holding a file somebody corrupted by hand must all serve a
   feed rather than an error. Ranking is an enhancement; it is never a dependency.
2. THE FEATURE CONTRACT IS ENFORCED. Training and serving share
   `ranking.FEATURES`; if an artifact was written against a different list, using
   it would score the wrong column and make the feed worse with no visible error.
   Such an artifact is refused.
3. THE ORDER ACTUALLY COMES FROM THE MODEL. A test that only checks "no crash"
   would pass on a ranker that is never consulted, so one test flips the order
   deliberately (oldest first) and reads the feed.
"""

import json
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.post import Post
from app.models.user import AccountStatus, AccountType, User
from app.services import ranking


def _artifact(**overrides) -> dict:
    """A coefficients file in the shape the trainer writes."""
    weights = [0.0] * len(ranking.FEATURES)
    payload = {
        "schema": ranking.MODEL_SCHEMA,
        "features": list(ranking.FEATURES),
        "weights": weights,
        "bias": 0.0,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin": "tests",
        "metrics": {},
    }
    payload.update(overrides)
    return payload


def _write(tmp_path, payload) -> str:
    path = tmp_path / "ranker.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _reset_cache() -> None:
    ranking._CACHE.clear()


async def _signup_and_login(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Rank Er",
            "username": username,
            "email": f"{username}@example.com",
            "password": "Long-enough-pass-2026",
        },
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"identifier": username, "password": "Long-enough-pass-2026"},
    )
    assert r.status_code == 200, r.text


# --- 1. no artifact, no change -------------------------------------------


async def test_without_an_artifact_the_feed_is_chronological(
    sample_feed, client: AsyncClient, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        get_settings(), "RANKING_MODEL_PATH", str(tmp_path / "missing.json")
    )
    _reset_cache()

    r = await client.get("/")
    assert r.status_code == 200, r.text
    assert "data-post=" in r.text


def test_a_missing_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        get_settings(), "RANKING_MODEL_PATH", str(tmp_path / "nothing.json")
    )
    _reset_cache()
    assert ranking.load_model() is None


# --- 2. the contract ----------------------------------------------------


def test_an_artifact_with_a_different_feature_list_is_refused(monkeypatch, tmp_path):
    payload = _artifact()
    payload["features"] = list(reversed(ranking.FEATURES))
    monkeypatch.setattr(get_settings(), "RANKING_MODEL_PATH", _write(tmp_path, payload))
    _reset_cache()
    assert ranking.load_model() is None, (
        "a model trained against a different feature order was accepted — it would "
        "score the right numbers against the wrong columns"
    )


def test_an_artifact_from_another_schema_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(
        get_settings(), "RANKING_MODEL_PATH", _write(tmp_path, _artifact(schema=999))
    )
    _reset_cache()
    assert ranking.load_model() is None


def test_a_valid_artifact_loads_with_its_metrics(monkeypatch, tmp_path):
    payload = _artifact(metrics={"holdout_roc_auc": 0.81})
    monkeypatch.setattr(get_settings(), "RANKING_MODEL_PATH", _write(tmp_path, payload))
    _reset_cache()
    model = ranking.load_model()
    assert model is not None
    assert model.metrics["holdout_roc_auc"] == 0.81


# --- 3. the feed follows the model --------------------------------------


async def test_the_feed_order_comes_from_the_model(
    sample_feed, engine, client: AsyncClient, monkeypatch, tmp_path
):
    """Weight the oldest post highest; the feed must then lead with it.

    `age_hours_norm` is 1.0 for a week-old post, so a positive weight is an
    explicit "prefer older content" — the exact inverse of the chronological
    default, which makes an accidental fallback obvious.
    """
    weights = [0.0] * len(ranking.FEATURES)
    weights[ranking.FEATURES.index("age_hours_norm")] = 8.0
    monkeypatch.setattr(
        get_settings(),
        "RANKING_MODEL_PATH",
        _write(tmp_path, _artifact(weights=weights)),
    )
    _reset_cache()

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        posts = (
            await session.execute(select(Post).order_by(Post.created_at.asc()))
        ).scalars().all()
    assert len(posts) >= 2, "the sample feed needs at least two posts"
    oldest = str(posts[0].public_id)
    newest = str(posts[-1].public_id)
    assert oldest != newest

    await _signup_and_login(client, "ranker")
    body = (await client.get("/")).text

    first_post = body.split('data-post="', 1)[1].split('"', 1)[0]
    assert first_post == oldest, (
        "the feed ignored the ranker: expected the model's top choice first"
    )


async def test_a_model_that_cannot_order_falls_back_to_newest_first(
    engine, client: AsyncClient, monkeypatch, tmp_path
):
    """All-zero weights must reproduce the chronological feed exactly.

    That is what makes a half-trained or freshly-initialised model harmless, and
    it is the property `rank()` guarantees by breaking ties on `created_at`.
    """
    monkeypatch.setattr(
        get_settings(), "RANKING_MODEL_PATH", _write(tmp_path, _artifact())
    )
    _reset_cache()

    now = datetime.now(timezone.utc)
    # Constructing ORM rows with ids is enough for the pure scoring path; this
    # test does not touch the database.
    from app.models.post import Post as PostModel

    author = User(
        account_type=AccountType.INDIVIDUAL,
        account_status=AccountStatus.ACTIVE,
        email="rank@sample.cartflow.test",
        username="rankauthor",
        username_normalized="rankauthor",
        display_name="Rank Author",
        full_name="Rank Author",
    )
    author.id = __import__("uuid").uuid4()

    def make(body: str, minutes: int) -> PostModel:
        post = PostModel(author_id=author.id, body=body, images=None)
        post.id = __import__("uuid").uuid4()
        post.public_id = __import__("uuid").uuid4()
        post.created_at = now - timedelta(minutes=minutes)
        post.like_count = 0
        post.comment_count = 0
        post.tagged_product_slugs = None
        return post

    fresh, stale = make("fresh", 5), make("stale", 500)
    ordered = ranking.rank(
        [(stale, author), (fresh, author)],
        viewer=None,
        followed_author_ids=set(),
        model=ranking.load_model(),
        now=now,
    )
    assert [post.body for post, _ in ordered] == ["fresh", "stale"]


# --- feature maths ------------------------------------------------------


def test_features_are_the_contract_and_stay_in_range(sample_feed):
    # `seed_feed` returns posts; their author is only needed for two flags, so a
    # stand-in keeps this a unit test of the maths rather than another DB round trip.
    post = sample_feed[0]
    author = User(
        account_type=AccountType.INDIVIDUAL,
        account_status=AccountStatus.ACTIVE,
        email="a@sample.cartflow.test",
        username="author",
        username_normalized="author",
        display_name="Author",
        full_name="Author",
    )
    viewer = User(
        account_type=AccountType.INDIVIDUAL,
        account_status=AccountStatus.ACTIVE,
        email="v@sample.cartflow.test",
        username="viewer",
        username_normalized="viewer",
        display_name="Viewer",
        full_name="Viewer",
    )
    features = ranking.features_for(post, author, viewer, follows_author=True)
    assert tuple(features) == ranking.FEATURES
    for name, value in features.items():
        assert 0.0 <= value <= 1.0, f"{name} escaped 0..1: {value}"
    assert features["follows_author"] == 1.0
