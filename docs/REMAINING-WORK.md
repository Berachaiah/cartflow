# CartFlow — what's left

Status as of 21 Aug 2026. The messaging arc is **built** — the section below is
now a record of what shipped and the four things about it that are still owed,
not a build list. Everything under it is the older backlog.

The approved plan this executed against lives at
`~/.claude/plans/memoized-mapping-abelson.md`.

---

## 1. Messaging (the current arc)

Started from *"let's do the real thing"* — real tables and a working inbox,
replacing the explainer page that only described the rules.

### Done and verified

| Piece | Files |
|---|---|
| Schema — 5 tables + `users.last_seen_at` | `app/models/conversation.py`, `app/models/report.py`, `app/database/migrations/versions/0009_messaging.py`, `app/models/__init__.py` |
| Every messaging query | `app/repositories/conversation.py` (~21 methods) |
| §6 state machine, presence, blocking | `app/services/messaging.py` |
| Reports + admin email | `app/services/reports.py`, `app/templates/emails/report_received.html`, `REPORTS_EMAIL` in `app/core/config.py` |
| Shared image helpers (moved out of `avatar.py`, no behaviour change) | `app/services/media.py` |
| Photo delivery URLs (`c_limit`, not the avatar's `c_fill`) | `app/integrations/cloudinary_client.py` → `build_photo_url` |
| Block check where `follow.py`'s docstring said to put it | `app/services/follow.py` → `resolve_public_user` |
| Wire payloads + the four ORM→JSON projections | `app/schemas/message.py` |

Full suite green after all of it: **317 passed**. The send path was
probe-tested against a deliberate double-tap race, and one real bug came out of
it — a request that lost the create race could slip a second message past §6.
Fixed by having `_open_conversation` return `(conversation, created)` so the
permission re-check is enforced by the type rather than by call-site discipline.

The reports probe covered validation, the happy path, note-folding on retry,
the 429 ceiling, SMTP failure leaving a visible unmailed row, and block-then-report
in both directions.

> Note: the session task list still shows **#14 in_progress**. It's finished —
> that entry is just stale.
>
> The **317 passed** above was the suite at that point; see §4 for the number
> that matters now.

### Also done, 19-21 Aug

| Piece | Files |
|---|---|
| Socket registry + fan-out (a service, not the ws router — a router may not import a router) | `app/services/realtime.py` |
| `/ws/messages` — cookie auth off the handshake, accept-then-close **4401**, `session_scope()` per frame | `app/routers/ws.py` |
| 14 REST endpoints (not the plan's 11 — `/candidates`, `/archive` and `/disappearing` were added) | `app/routers/messages.py` |
| Disappearing messages: 48 h default ON, per conversation, snapshot-at-send, read filter + opportunistic purge sparing open reports | `app/models/conversation.py`, `app/services/messaging.py` → `purge_expired`, `0010_disappearing_messages` |
| Two-pane inbox and thread chrome — furniture only, no conversation rendered server-side | `app/templates/messages.html`, `app/templates/partials/thread.html` |
| The one renderer: rows, bubbles, presence, typing, countdowns, sheets, socket client | `app/static/js/cartflow-messages.js` |
| `/messages` (+ `?share=`, `?share_user=`) and `/messages/@{username}` | `app/routers/pages.py` |
| Unread badge, live off `/api/messages/unread` | `app/templates/base.html` |
| Inbox pagination — server-computed `has_more` by one-row over-fetch, not `len(items) == limit` | `app/schemas/message.py`, `app/services/messaging.py`, `app/routers/messages.py` |
| Four ways into a conversation: profile Message button, profile share sheet, home post share, product page share | `app/templates/profile.html`, `app/templates/home.html`, `app/templates/product.html` |
| Tests | `tests/test_messaging.py`, `tests/test_blocking.py`, `tests/test_disappearing_messages.py`, `tests/test_inboxes.py` (4 stale tests inverted rather than deleted) |
| Docs | `docs/product/10-messaging.md` Implementation Status, `scripts/seed_sample_social.py` |

The design reasons behind all of it now live in the module docstrings rather than
here — `realtime.py` on why the registry is a service, `ws.py` on accept-then-close
and why typing gets a per-frame participation check, `messaging.py` on the §6 state
machine, `purge_expired` on the two halves of disappearing, and
`cartflow-messages.js` on ONE RENDERER.

### Still owed on messaging

1. **Put `alembic upgrade head` in the deploy step.** The database is current as
   of 2026-11-23 — `0013_products` applied — but nothing applies migrations
   automatically, and the failure that costs you is invisible to a green test
   run: the suite builds its schema from `create_all`, so it passes whether or
   not production has the table. This bit once already (`products` was missing
   from Supabase while every test passed).
2. **One worker, or fix the fan-out.** The socket registry is a per-process dict,
   so a message sent on one worker cannot reach a socket held by another.
   `docs/engineering/31-deployment-and-infrastructure.md:234` recommends multiple
   workers. The failure mode is quiet — messages still send, they just stop
   arriving live for some pairs — and reconnect-and-refetch masks it, which is
   what makes it quiet.
3. **No cron for `purge_expired`.** Correct without one (the read filter is the
   correctness half), but storage is only reclaimed in conversations somebody
   still visits. The callable already takes `conversation_id=None` for a
   whole-table pass.
4. **The manual two-account pass** in §4 below, which I can't do from here.

### Not being built, on purpose

Shared **posts** and shared **events** (§12, §14) — no tables, so the card would
link nowhere. The Notes row from the screenshots — no table, and it's the most
recognisably Instagram element on the screen.

---

## 2. Waiting on you

- **Logo → SVG** (task #12). Gated by *"don't implement it yet, till I've
  confirmed that we got the svg right."*
- **Clear all users.** Irreversible, and I need the target confirmed first:
  live Supabase Postgres, or `./dev_preview.db`?
- **Restart the dev server** and eyeball the messaging screens in both themes
  once #16 lands. I don't start servers or drive the browser here.
- `.env` keys stay yours to paste — Google OAuth and Cloudinary both.

---

## 3. Older backlog

- **Flutterwave.** `PAYMENT_PROVIDER` and its references across ~10 files still
  say the old provider.
- ~~**Compile Tailwind to a static stylesheet.**~~ **Done, 9 Sep 2026.**
  `tailwind.config.js` (a verbatim port of the inline config that was in
  `base.html`) builds `app/static/css/tailwind.css`, and `base.html` links it
  where the `cdn.tailwindcss.com` script used to sit — above `cartflow-ui.css`,
  which is written to override Preflight. `https://cdn.tailwindcss.com` came out
  of the CSP `script-src` with it (`app/core/middleware.py`).

  Rebuild after touching any template, any file in `app/static/js`, or
  `app/routers/pages.py` — those are the three content globs:

  ```
  npx tailwindcss -i app/static/css/tailwind-input.css \
                  -o app/static/css/tailwind.css --minify
  ```

- ~~**Self-host the fonts.**~~ **Done, 9 Sep 2026.** `scripts/vendor_fonts.py`
  downloads Inter, Fraunces and Material Symbols into `app/static/fonts/` (11
  woff2 files, 1.4 MB, of which Material Symbols alone is 1.1 MB) and writes
  `app/static/css/fonts.css` with every `url()` rewritten to a local path.
  `base.html` links that one file where the two `fonts.googleapis.com` tags and
  their preconnects used to be, and `fonts.googleapis.com` / `fonts.gstatic.com`
  came out of the CSP `style-src` and `font-src`.

  Re-run it if the font URLs in `base.html` ever change; it is idempotent, and
  `--force` re-downloads. **Regenerate rather than hand-editing `fonts.css`** —
  it carries Google's own `.material-symbols-outlined` rule, and that rule's
  `'liga'` setting is what turns the markup `<span ...>storefront</span>` into a
  picture instead of the literal word. `cartflow-ui.css` only overrides
  font-size and will not save you.

  `tests/test_vendored_assets.py` guards the failure mode, which is silent: a
  half-run script or a deleted woff2 leaves a `url()` pointing at a 404, the
  browser falls back, and the page still renders — with the icons quietly
  turned back into English words.

  Verified in-browser at 375×812: `tailwind.css`, `fonts.css` and the woff2
  files all 200 from `'self'`, and the ligatures collapse — `person` (6 chars)
  and `visibility` (10 chars) both render 20 px wide, which they could only do
  as single glyphs.

- ~~**Twemoji.**~~ **Removed, 9 Sep 2026.** It was the last external
  dependency, and it was dead: `cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2`
  returns a hard 404 (verified off-sandbox), because the upstream repo was
  archived. Nobody had noticed, because it was written as a progressive
  enhancement — `cfParseEmoji` is guarded on `window.twemoji`, so it no-opped
  and the OS emoji rendered. Good failure mode; bad thing to keep, since it was
  a request on every page load that could only 404.

  Removed rather than repointed at a maintained fork. It bought consistent
  emoji only for **online** users, at the price of a third-party origin and one
  SVG fetch per distinct emoji — and the point of this whole arc was an app that
  renders without internet. The emoji involved are decorative (🔥 on a Trending
  pill, ✨, ⚡); native rendering is fine.

  `window.cfParseEmoji` is **kept as a documented no-op**, because 35 call sites
  across 12 files invoke it after injecting content. They cost nothing — the
  guard fails fast — and they are the seam: restoring Twemoji later means adding
  a `<script>` back in `base.html`, not 35 edits. Self-hosting would mean
  vendoring the SVG set into `app/static` the way the fonts were done, which is
  a far bigger job than the fonts (thousands of files, not eleven).

  With it gone, **the CSP has no third-party origin in any directive.**
  `script-src` is now `'self' 'unsafe-inline'`, and the one remaining obstacle
  to dropping `'unsafe-inline'` is ordinary work: nonce the five inline blocks
  (theme bootstrap, skeleton dismissal, the emoji no-op, per-page scripts). The
  thing that used to make that impossible — a CDN injecting its own scripts —
  no longer exists.

  Two tests in `tests/test_security_headers.py` were inverted rather than
  deleted to match (`test_no_page_loads_an_external_script`,
  `test_no_page_loads_an_external_stylesheet`); both now assert zero.

  **What this does not mean:** the app still needs the network for *images*.
  `img-src` keeps a bare `https:` for Cloudinary, and the demo feed pulls from
  `images.unsplash.com` and `picsum.photos`. Offline, a page now renders
  correctly — layout, type and icons — with blank photos.
- **Type scale** on `profile_not_found.html` and `stub.html` — the last two pages
  not on the macro scale.
- **Mini pages** still missing: saved/liked, and a generic 404.

---

## 4. Verification still owed

1. Full suite, backgrounded (~226 s, exceeds the 120 s default):
   `./venv/bin/python -m pytest -q -p no:logging --tb=short`
2. `alembic upgrade head` against Postgres, and confirm SQLite `create_all`
   produces the same objects — tests and `dev_preview.db` use the latter, so the
   models and `0009_messaging.py` / `0010_disappearing_messages.py` have to stay
   in step.
3. Manual two-account pass: first message arrives live without a reload, reply
   flips the request to accepted, a second message before acceptance reads 409,
   then decline, block, report, and confirm the mail lands.
4. All of #3 again in light theme, at phone width, composer clearing the home bar.
5. Watch the console for a CSP `connect-src` block on the WebSocket.
   `app/core/middleware.py:123` is `'self'`, which per CSP3 covers same-origin
   `wss:` — widen only if a real block appears, and never to a bare `ws:`.
