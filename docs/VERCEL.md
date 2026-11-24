# Deploying CartFlow to Vercel

CartFlow is a FastAPI + Jinja app, so on Vercel it runs as one Python serverless
function (`api/index.py`) that serves every page, API route and `/static` file.
`vercel.json` routes `/(.*)` to that function and bundles the templates and
static assets with it.

## 1. Push to GitHub, then import

1. Commit and push (the repository's `.gitignore` already keeps `.env`, the
   SQLite preview databases and the captured session cookies out).
2. In Vercel: **Add New → Project → Import** the GitHub repo.
3. Framework preset: **Other**. Do not set a build command or output directory —
   `vercel.json` already describes the build.
4. Deploy once, then add the environment variables below and redeploy. Vercel
   only injects variables that exist at build time for the build step and at
   runtime for the function.

## 2. Environment variables

Copy these into **Project → Settings → Environment Variables** (Production and
Preview). Values are never committed.

| Variable | Required | Notes |
| --- | --- | --- |
| `APP_ENV` | yes | `production` |
| `APP_SECRET_KEY` | yes | 32+ random characters. `production` refuses to boot with the default placeholder or a short key (see `app/core/config.py`). |
| `APP_BASE_URL` | yes | The deployment URL, e.g. `https://cartflow.vercel.app`, no trailing slash. Used for OAuth redirects, email links and the payment `redirect_url`. |
| `DATABASE_URL` | yes | Supabase Postgres, `postgresql+asyncpg://...` |
| `DB_SSL` | recommended | `require` (default) or `verify-full` + `DB_SSL_CA_FILE` |
| `SMTP_*`, `EMAIL_FROM` | for email | Verification and password-reset mail |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | optional | Google sign-in; register `{APP_BASE_URL}/api/auth/google/callback` |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | for photos | Avatars, message photos and post photos. All three, or the upload routes answer 503 and the UI hides its photo controls; text-only posts still work. |
| `PAYMENT_PROVIDER` | optional | `flutterwave` (default) or `squad` — the pre-selected gateway |
| `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_PUBLIC_KEY`, `FLUTTERWAVE_ENCRYPTION_KEY`, `FLUTTERWAVE_CURRENCY`, `FLUTTERWAVE_WEBHOOK_HASH` | for Flutterwave | `FLUTTERWAVE_WEBHOOK_HASH` is the dashboard's secret hash; without it webhooks are refused (401) |
| `SQUAD_SECRET_KEY`, `SQUAD_PUBLIC_KEY`, `SQUAD_CURRENCY`, `SQUAD_API_BASE` | for Squad | Test keys use `https://sandbox-api-d.squadco.com`; live keys use `https://api-d.squadco.com` |

## 3. Database

Run the migrations once against Supabase from your machine — the function has no
shell:

```bash
DATABASE_URL="postgresql+asyncpg://..." ./.venv/Scripts/python.exe -m alembic upgrade head
```

The local SQLite file (`dev_preview.db`) must not be deployed: Vercel's filesystem
is read-only apart from `/tmp`, so a SQLite database there would lose every write
and reset on each cold start. Postgres is the only correct target.

## 4. Payment callbacks

Both gateways redirect the browser back to `{APP_BASE_URL}/payments/callback`, and
Squad posts its webhook to `{APP_BASE_URL}/webhooks/squad`. So:

* Flutterwave dashboard → Settings → Webhooks: set the URL to
  `{APP_BASE_URL}/webhooks/flutterwave` and put the same secret hash in
  `FLUTTERWAVE_WEBHOOK_HASH`.
* Squad dashboard → Webhooks: set the URL to `{APP_BASE_URL}/webhooks/squad` and
  point it at the **same account as `SQUAD_SECRET_KEY`**, because the signature is
  an HMAC keyed with that secret.

## 5. What does not work on this host

These are limits of the platform, not of the app:

* **WebSockets.** The messaging socket (`/ws/...`) needs a persistent connection;
  Vercel functions do not hold one. Messaging falls back to its polling/
  reconnect path, so sending still works, but live "typing…" and presence do not.
  Put Cloud Run / Railway / a small VPS behind the domain if live chat must be
  shown in a demo.
* **Long requests.** `maxDuration` is 30s in `vercel.json`; a gateway call that
  hangs returns a 504 rather than waiting. Both payment clients already time out
  at 20–25s.
* **Background jobs.** Nothing long-running can live in the function; scheduled
  work has to be Vercel Cron hitting a route, or a separate worker.

## 6. Installable app (PWA)

`/manifest.webmanifest` and `/sw.js` are served by the function at the site
root (see `app/main.py`). That is deliberate: a service worker only controls
pages under its own URL, so serving it from `/static/` would register it and let
it cache nothing that matters.

The worker caches the app's own static assets and an offline card, and never
caches a page or an API response — every page here renders per account, so a
cached document would show one person's messages or orders to the next. A
navigation that cannot reach the network shows `/static/offline.html` instead of
a stale copy, which in a marketplace with prices is the honest answer.

Changing `public/sw.js` requires bumping `VERSION` in `app/static/sw.js`; the
activate handler deletes every cache that does not match it.

## 7. Verify after deploying

```bash
curl -i https://<deployment>/health/live     # {"status":"ok"}
curl -i https://<deployment>/health/ready    # {"status":"ok","database":"reachable"}
curl -i https://<deployment>/manifest.webmanifest   # application/manifest+json
curl -i https://<deployment>/sw.js                  # text/javascript, Service-Worker-Allowed: /
```

Then open `/marketplace` (static CSS/JS and product photos load), sign in, and
check that `/orders` renders. A 500 on every page usually means `DATABASE_URL` or
`APP_SECRET_KEY` is missing; `/health/ready` reporting `"degraded"` means the
function is up but Postgres is not reachable (wrong password, missing `?sslmode`,
or a Supabase IP restriction).
