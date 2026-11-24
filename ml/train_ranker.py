"""Train the Home-feed ranker, recorded in MLflow (doc 18 §25).

WHAT THIS IS. A logistic-regression ranker over the nine signals in
`app/services/ranking.py`, trained on the likes and follows CartFlow already
stores. It answers one question per (viewer, post): how likely is this viewer to
like this post? The feed uses the score to order candidates.

WHY A LINEAR MODEL, HONESTLY. The data in this database is roughly a hundred
rows. Anything with more capacity than a logistic regression would memorise the
demo and produce a feed nobody can explain later — and doc 18 §21 promises the
user an explanation ("You follow this business"). Nine coefficients can be
printed, argued about and pasted into that answer; a gradient-boosted ensemble
cannot. When there is real traffic, this is the baseline those models have to
beat, and MLflow is where that comparison lives.

WHY TRAINING IS A SEPARATE PROCESS WITH ITS OWN VENV. `mlflow` + `scikit-learn` +
`numpy` is around a gigabyte unpacked, and nothing in the request path needs it:
serving reads the coefficients. Installing it into the app's environment would
make every deploy heavier and every cold start slower to support a job that runs
weekly. `requirements-ml.txt` exists for exactly this split.

WHY IT IS NOT ON VERCEL. Training needs a writable filesystem, a DB connection
that outlives 30 seconds, and (optionally) a tracking server. Run it where jobs
run — a laptop, a scheduled machine, GitHub Actions — and commit/upload only the
resulting `ranker.json`.

USAGE
    python -m ml.train_ranker                  # train + log to ./mlruns
    python -m ml.train_ranker --register       # also register a model version
    python -m ml.train_ranker --no-mlflow      # just write the artifact
    python -m ml.train_ranker --out ml/artifacts/ranker.json

The script is idempotent: every run writes a complete artifact and never appends
to the previous one, so a bad run is undone by re-running a good one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.database.session import connect_args_for
from app.models.post import Post, PostLike, PostStatus
from app.models.user import AccountStatus, User, UserFollow
from app.services import ranking

DEFAULT_OUT = Path("ml/artifacts/ranker.json")
EXPERIMENT = "cartflow-feed-ranking"


class NoData(RuntimeError):
    """Raised when the database cannot support a training run.

    A zero-row dataset is not a modelling problem to work around — it means the
    script pointed at the wrong database, and a model trained on it would be
    empty. Failing loudly here is what keeps a meaningless artifact from reaching
    the feed.
    """


async def collect(database_url: str) -> dict:
    """Read the signals, then build one feature row per (viewer, post) pair.

    `features_for` is the SERVING function, imported rather than reimplemented:
    if training used its own copy of the feature maths, a model could be trained
    on one definition and served against another and nobody would notice until
    the feed got strange.
    """
    engine = create_async_engine(
        database_url, connect_args=connect_args_for(database_url), future=True
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as session:
            users = (
                await session.execute(
                    select(User).where(
                        User.deleted_at.is_(None),
                        User.account_status.notin_(
                            (AccountStatus.SUSPENDED, AccountStatus.DELETED)
                        ),
                    )
                )
            ).scalars().all()
            posts = (
                await session.execute(
                    select(Post, User)
                    .join(User, User.id == Post.author_id)
                    .where(
                        Post.deleted_at.is_(None),
                        Post.status == PostStatus.PUBLISHED.value,
                        User.deleted_at.is_(None),
                    )
                    .order_by(Post.created_at.desc())
                )
            ).all()
            likes = set(
                (await session.execute(select(PostLike.post_id, PostLike.user_id))).all()
            )
            follows = set(
                (
                    await session.execute(select(UserFollow.follower_id, UserFollow.following_id))
                ).all()
            )
    finally:
        await engine.dispose()

    if not posts:
        raise NoData("no published posts to learn from")
    if not likes:
        raise NoData(
            "no post_likes rows — a ranker trained on zero positives would score everything alike"
        )

    now = datetime.now(timezone.utc)
    rows, labels, viewers = [], [], []
    for viewer in users:
        for post, author in posts:
            followed = (viewer.id, author.id) in follows
            feats = ranking.features_for(
                post, author, viewer, follows_author=followed, now=now
            )
            rows.append([feats[name] for name in ranking.FEATURES])
            labels.append(1 if (post.id, viewer.id) in likes else 0)
            viewers.append(viewer.id)

    return {
        "rows": rows,
        "labels": labels,
        "viewers": viewers,
        "n_users": len(users),
        "n_posts": len(posts),
        "n_likes": len(likes),
        "n_follows": len(follows),
    }


def train(rows: list[list[float]], labels: list[int]):
    """Fit the ranker and return (model, metrics). sklearn stays out of the app."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
    from sklearn.model_selection import train_test_split

    X = np.asarray(rows, dtype=float)
    y = np.asarray(labels, dtype=int)

    positives = int(y.sum())
    if positives == 0 or positives == len(y):
        raise NoData(
            f"labels are all {int(y[0])} ({len(y)} rows) — there is nothing to separate"
        )

    # Stratified so a holdout always contains both classes; with a small demo
    # dataset an unlucky split is otherwise the difference between a metric and a
    # crash.
    try:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
    except ValueError:
        X_tr, X_te, y_tr, y_te = X, X, y, y

    model = LogisticRegression(max_iter=2000, class_weight="balanced")
    model.fit(X_tr, y_tr)

    proba = model.predict_proba(X_te)[:, 1]
    metrics = {
        "rows": float(len(y)),
        "positives": float(positives),
        "positive_rate": float(positives / len(y)),
        "holdout_rows": float(len(y_te)),
        "train_log_loss": float(log_loss(y_tr, model.predict_proba(X_tr)[:, 1])),
        "holdout_log_loss": float(log_loss(y_te, proba)),
        "holdout_accuracy": float(accuracy_score(y_te, (proba >= 0.5).astype(int))),
    }
    # AUC is undefined with one class in the holdout; report the metric that is
    # true rather than a 0.5 placeholder that reads like a real measurement.
    if len(set(y_te.tolist())) > 1:
        metrics["holdout_roc_auc"] = float(roc_auc_score(y_te, proba))

    return model, metrics


def artifact_from(model, metrics: dict, *, origin: str) -> dict:
    return {
        "schema": ranking.MODEL_SCHEMA,
        "features": list(ranking.FEATURES),
        "weights": [float(w) for w in model.coef_[0]],
        "bias": float(model.intercept_[0]),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin": origin,
        "metrics": metrics,
    }


def log_to_mlflow(
    artifact: dict,
    metrics: dict,
    *,
    args,
    dataset: dict,
) -> str | None:
    """Record the run (params, metrics, contract, artifact) and return its id."""
    try:
        import mlflow
        from mlflow.tracking import MlflowClient
    except ImportError:
        print(
            "mlflow is not installed in this interpreter — artifact written without "
            "tracking. Install requirements-ml.txt to record the run.",
            file=sys.stderr,
        )
        return None

    settings = get_settings()
    mlflow.set_tracking_uri(
        args.tracking_uri or settings.MLFLOW_TRACKING_URI or "file:./mlruns"
    )
    mlflow.set_experiment(args.experiment)

    with mlflow.start_run(run_name=f"ranker-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}") as run:
        mlflow.log_params(
            {
                "model": "LogisticRegression",
                "features": ",".join(ranking.FEATURES),
                "class_weight": "balanced",
                "test_size": 0.25,
                "random_state": 42,
                "database": args.database_url.split("@")[-1].split("/")[0],
            }
        )
        mlflow.log_metrics(metrics)
        mlflow.set_tags(
            {
                "dataset.users": str(dataset["n_users"]),
                "dataset.posts": str(dataset["n_posts"]),
                "dataset.likes": str(dataset["n_likes"]),
                "artifact.schema": str(ranking.MODEL_SCHEMA),
            }
        )
        # The contract is logged beside the coefficients so a future reader can
        # tell which column meant what without checking out this commit.
        mlflow.log_dict(
            {"features": list(ranking.FEATURES), "schema": ranking.MODEL_SCHEMA},
            "feature_contract.json",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ranker.json"
            path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
            mlflow.log_artifact(str(path))
        mlflow.log_dict(artifact, "ranker_document.json")

        run_id = run.info.run_id

        if args.register:
            # The registry records WHERE this artifact came from and which version
            # is current — it is the audit trail, not the serving path. The app
            # reads `ranker.json` straight from disk, so promoting a version is
            # exporting it (see docs/MLFLOW.md).
            client = MlflowClient()
            try:
                client.create_registered_model(args.model_name)
            except Exception:  # already exists — fine, and races are harmless
                pass
            version = client.create_model_version(
                name=args.model_name,
                source=f"runs:/{run_id}/ranker.json",
                run_id=run_id,
                description=(
                    "CartFlow feed ranker coefficients. Not a pyfunc model: "
                    "app/services/ranking.py scores with these weights directly."
                ),
            )
            client.set_model_version_tag(args.model_name, version.version, "schema", str(ranking.MODEL_SCHEMA))
            print(f"registered {args.model_name} version {version.version}")

    return run_id


async def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Train and log the CartFlow feed ranker.")
    parser.add_argument("--database-url", default=settings.DATABASE_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tracking-uri", default=None)
    parser.add_argument("--experiment", default=EXPERIMENT)
    parser.add_argument("--model-name", default=settings.MLFLOW_MODEL_NAME)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args(argv)

    try:
        dataset = await collect(args.database_url)
    except NoData as exc:
        print(f"cannot train: {exc}", file=sys.stderr)
        return 2

    rows, labels = dataset["rows"], dataset["labels"]
    print(
        f"dataset: {len(rows)} (viewer, post) rows | "
        f"{dataset['n_users']} users | {dataset['n_posts']} posts | "
        f"{sum(labels)} positive"
    )

    try:
        model, metrics = train(rows, labels)
    except NoData as exc:
        print(f"cannot train: {exc}", file=sys.stderr)
        return 2

    artifact = artifact_from(model, metrics, origin="mlflow")
    if not args.no_mlflow:
        run_id = log_to_mlflow(artifact, metrics, args=args, dataset=dataset)
        if run_id:
            artifact["origin"] = f"mlflow run {run_id}"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    print("metrics:")
    for key, value in sorted(metrics.items()):
        print(f"  {key:>20}: {value:.4f}")
    print("weights:")
    for name, weight in zip(ranking.FEATURES, artifact["weights"]):
        print(f"  {name:>20}: {weight:+.4f}")
    print(f"bias: {artifact['bias']:+.4f}")
    print(f"artifact: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
