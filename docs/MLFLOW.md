# MLflow in CartFlow

How Home's feed gets a model, where MLflow sits, and what is deliberately not
built yet. Product context: `docs/product/18-recommendation-and-ranking.md`
(§5 signals, §25 "MLFlow recommendation models").

---

## 1. The problem MLflow is answering

The feed ships as chronological, which is honest but dumb: a post from a shop you
follow and a stranger's post from six days ago are treated identically. Doc 18 §5
says what *should* matter — following, likes, comments, freshness, campus
relevance — and §25 says the ranking model is trained with MLflow.

So the questions that need an answer are not "how do we score a post" but:

- Which version of the model is live, and what data produced it?
- Was this week's model better than last week's?
- When a ranking looks wrong, can we see the coefficients behind it?

MLflow answers those. It is **not** in the request path: no feed render calls
MLflow, and the web app does not depend on it.

## 2. Shape of the system

```
              ┌──────────────────────────────────────────────┐
              │  python -m ml.train_ranker          (weekly │
              │  reads likes + follows + posts      or on   │
              │  fits LogisticRegression            demand) │
              └───────────────┬──────────────────────────────┘
                              │
              ┌───────────────▼───────────────┐
              │ MLflow tracking store          │  experiments, params,
              │ (sqlite:///mlflow.db, or a     │  metrics, artifacts,
              │  server: `mlflow server`)      │  model registry versions
              └───────────────┬───────────────┘
                              │ exports
              ┌───────────────▼───────────────┐
              │ ml/artifacts/ranker.json       │  ~1 KB of coefficients
              └───────────────┬───────────────┘
                              │ read at request time
              ┌───────────────▼───────────────┐
              │ app/services/ranking.py        │  bias + Σ w·x, pure Python
              │ app/services/posts.py feed()   │  ranks a candidate pool
              └───────────────────────────────┘
```

Two things follow from that drawing, and both are deliberate:

**Serving reads a JSON file, not an MLflow model.** A pickled sklearn pipeline
means importing `mlflow` + `scikit-learn` + `numpy` on the first request after
every cold start, on a host with a 30-second ceiling and a read-only filesystem.
The artifact here is `{"features", "weights", "bias"}` and scoring is nine
multiplications. MLflow stays the registry and the audit trail.

**Training is a separate process in a separate environment.**
`requirements-ml.txt` is not part of the deploy. Training needs a writable
filesystem, a database connection that outlives 30 seconds, and MLflow itself —
none of which a Vercel function has.

## 3. The features

Defined once, in `app/services/ranking.py::FEATURES`, and imported by the trainer.
If training and serving each defined their own order, a model would score the
right numbers against the wrong columns and nobody would notice until the feed got
strange. `load_model()` refuses any artifact whose feature list does not match.

| feature | meaning | source |
| --- | --- | --- |
| `follows_author` | viewer follows the author | `user_follows` (doc 18 §5) |
| `same_organization` | same campus/university | `users.organization_id` (§12) |
| `author_is_seller` | shop account vs person | `users.is_seller` |
| `age_hours_norm` | freshness, 0 = now, 1 = a week old | `posts.created_at` (§14) |
| `like_count_norm` | engagement, saturating at 100 | `posts.like_count` (§5) |
| `comment_count_norm` | ditto, saturating at 50 | `posts.comment_count` (0 today — comments are unbuilt) |
| `has_media` | photo post | `posts.images` |
| `has_tagged_product` | shop content with a destination | `posts.tagged_product_slugs` (§20) |
| `caption_length_norm` | very short captions are often noise | `posts.body` |

Signals doc 18 §5 lists that are **not** here — saves, shares, reposts,
watch-time, "see fewer like this": those tables do not exist. A constant column
would train a weight on nothing, so they are omitted rather than faked.

## 4. Running it

```bash
# once, in an isolated environment (mlflow + sklearn + the app's models)
python -m venv .venv-ml
.venv-ml/Scripts/python -m pip install -r requirements-ml.txt   # or: source .venv-ml/bin/activate

# train against the dev database, record the run, register a version
.venv-ml/Scripts/python -m ml.train_ranker \
    --database-url "sqlite+aiosqlite:///./dev_preview.db" \
    --tracking-uri "sqlite:///mlflow.db" \
    --register

# or against Supabase (uses DATABASE_URL from .env)
.venv-ml/Scripts/python -m ml.train_ranker --register
```

Useful flags: `--out` (where the artifact lands), `--no-mlflow` (train and write
the artifact with no tracking), `--experiment`, `--model-name`,
`--tracking-uri`.

Inspect the runs without a browser:

```bash
.venv-ml/Scripts/mlflow ui --backend-store-uri sqlite:///mlflow.db
```

For a shared tracking server, run `mlflow server --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlartifacts` somewhere durable and point `MLFLOW_TRACKING_URI` at it. Nothing else changes: the artifact is still exported to `ml/artifacts/ranker.json`.

## 5. Configuration

| setting | default | who reads it |
| --- | --- | --- |
| `RANKING_ENABLED` | `true` | app — a kill switch; `false` restores chronological order without a deploy of code |
| `RANKING_MODEL_PATH` | `ml/artifacts/ranker.json` | app — where the coefficients live |
| `MLFLOW_TRACKING_URI` | none → `file:./mlruns` | trainer only |
| `MLFLOW_MODEL_NAME` | `cartflow-feed-ranker` | trainer only |

The artifact is **gitignored**: it is generated per database, and committing one
fitted to demo likes would ship it to production. Without the file the feed serves
chronological order, which is the right default until a model has been trained on
real traffic. To promote one, copy `ml/artifacts/ranker.json` into the deploy
(commit it, or upload it in the build step) and set `RANKING_MODEL_PATH` if it
lives somewhere else. Replacing the file is enough — the cache is keyed on mtime,
so no restart is needed.

## 6. What happens at request time

`app/services/posts.py::feed()`:

1. Signed out → chronological, always. Personalization needs a viewer.
2. Signed in, no artifact → chronological, exactly the old query.
3. Signed in, artifact present → fetch a candidate pool
   (`limit × 3`, capped at 60), score each `(viewer, post)` pair, sort by score
   with `created_at` as the tie-break so an all-zero model reproduces the
   chronological feed exactly.

Ranking only reorders what the pool contains — it cannot invent reach for a post
older than the pool. That is the safe behaviour while the catalogue is small, and
the place to change first when there is real traffic.

## 7. A real run

Trained on `dev_preview.db` (7 users, 10 posts, 7 likes, 70 viewer×post pairs):

```
holdout_roc_auc     0.7500
holdout_log_loss    0.6162
positive_rate       0.1000

follows_author       +1.2213
like_count_norm      +0.9018
has_tagged_product   +0.9018
author_is_seller     +0.6400
has_media            +0.3374
same_organization    -0.6507
```

Read that honestly: AUC 0.75 on **18 holdout rows** with 7 positives overall is a
sanity check, not evidence of quality — a single flipped pair moves it by ~0.05.
`follows_author` carrying the largest positive weight is the expected direction
and is the one result worth trusting. `same_organization` coming out negative is
almost certainly the tiny sample: nearly every user in the seed shares a campus,
so the column barely varies.

## 8. What is not built

- **No automatic retraining.** No scheduler, no CI job. Training is a command a
  person runs, because a model silently promoted by cron at 3 a.m. is a feed
  nobody has looked at.
- **No online evaluation.** No A/B assignment, no interleaving, no impression
  logging — so there is no measured lift to report. Adding impression logging is
  the prerequisite for the next model, not a nice-to-have.
- **No embeddings or collaborative filtering.** Nine features, one linear model;
  doc 18's §8 matrix factorization needs interaction volume this app does not have.
- **No "why am I seeing this" UI.** The service exposes per-post features, so the
  explanation is available; the surface that renders it is not built.
- **The registry stores an artifact, not a pyfunc model.** Versions are the audit
  trail for "which coefficients are live"; the app loads the JSON directly. Do not
  `mlflow models serve` from this registry entry.
