# CartFlow Docs

## Source of truth

The **Markdown** files in `product/` and `engineering/` are the authoritative,
current specification. They are kept in sync with the code.

The `.docx` PRD chapters (e.g. `CartFlow_PRD_V1_Chapter_*.docx`) are **frozen
V1 exports for reference only**. They predate the multi-persona auth work
(identity-vs-capability accounts, Individual persona, Google Sign-In,
"Start selling", graduation) and are **known to be out of date**. Do not treat
them as current — when a `.docx` and a `.md` disagree, the `.md` wins.

_Last reconciled with code: November 23, 2026._

Status vocabulary used below: **Done** (real tables and routes, wired end to end),
**Partial** (the page and its behaviour exist, but some of what it shows has no
storage behind it), **Not built** (no schema, no route — at most an honest
placeholder or an explainer). A feature is only **Done** if restarting the app
does not lose the data it claims to manage.

## What is built, and where

Each product doc listed below ends with an **"Implementation Status — as built"**
section naming the route, the template, the tests, and — the part that matters most
when picking up work — **what is deferred and why**. Read that section before
building against a chapter: the spec describes V1, not today.

| Doc | Route | Template | Status |
|---|---|---|---|
| 03, 05 — accounts & auth | `/signup`, `/login`, `/forgot-password`, `/reset-password`, `/verify-email` | `signup.html`, `login.html`, … | **Done.** Multi-persona + student signup, Google Sign-In, cookie sessions, password reset by OTP, email verification, login lockout, graduation, student→business upgrade |
| 04 — navigation & IA | all | `base.html` | **Done.** Sidebar, bottom tab bar, top bar, create sheet |
| 06 — home feed | `/` | `home.html` | **Partial.** Chrome, identity, caption rendering (`#hashtag` → `/discover?tag=`, `@mention` → `/@handle`) and the stories rail are real; the posts themselves are placeholder — there is no `posts` table |
| 07 — discover & search | `/discover` | `discover.html` | **Partial.** Page, `?q=` / `?tag=` handling and every explore section render; search runs client-side over placeholder data — no index (doc 38 unbuilt) |
| 08 — profiles | `/@handle` | `profile.html` | **Done, real data.** Follows (`user_follows`), edit profile, avatar upload, start selling, graduation |
| 09 — stories | — | (rail in `home.html`) | **Not built.** No `stories` table; the rail and viewer run on a curated placeholder list, and the create sheet says so |
| 10 — messaging | `/messages`, `/messages/@{username}` | `messages.html`, `partials/thread.html` | **Done, and beyond the spec.** Real tables (`conversations`, `conversation_participants`, `messages`, `user_blocks`, plus pins / wallpapers / chat products), 28 REST endpoints, `/ws/messages`, disappearing messages, blocking, reports. Operational gaps are listed in `REMAINING-WORK.md` §1 — not missing features |
| 11 — activity & notifications | `/notifications` | `notifications.html` | **Partial.** Follow events are genuine, rendered off the `user_follows` edge; the other five categories have no `notifications` table and no push/email fan-out |
| 12 — shop & products | `/marketplace`, `/product/{slug}` | `shop.html`, `product.html` | **Partial.** Front end and slug routing done (`404` for unknown slugs, not a crash); the catalogue is the placeholder list in `app/services/catalog.py` — no `products` table, so a product cannot be created or sold |
| 13 — cart & checkout | `/marketplace` | (`#cartSheet`) | **Cart only.** Line items live in `localStorage` (`cartflow-cart`); nothing survives a cleared browser or a second device. Checkout deliberately stops before payment |
| 14 — orders & delivery | `/orders` | `orders.html` | **Not built.** UI plus the doc's rules as a reference sheet; no `orders` table, history renders honestly empty |
| 15 — payments, escrow, payouts | — | — | **Not built.** No provider client and no ledger; `PAYMENT_PROVIDER` is a setting nothing reads yet |
| 16 — business hub | `/dashboard` | `dashboard.html` | **Partial.** Three server-rendered states and business-profile editing are real against `organizations`; metrics are honest zeros because nothing can be sold yet |
| 17 — events & ticketing | — | — | **Not built.** Milestone 2 — no event tables, no route, no scanner |
| 18 — recommendation & ranking | — | — | **Not built.** Every "suggested" / "trending" section is curated, not scored |

### Built outside the numbered chapters

These have schema and routes of their own and are easy to miss when reading the
table above, because no product chapter owns them:

| Area | Route | Status |
|---|---|---|
| Organization taxonomy + university directory | `/universities`, `/api/organizations/*` | **Done.** `organization_groups`, `organization_types`, `organizations`, `universities`, seeded by script. The older `/api/universities/search` and `/resolve` still answer but are marked `deprecated=True` — the taxonomy replaced them, so build new work against `/api/organizations/*` |
| Organization / signup requests | `/request-organization`, `POST /api/organizations/requests` | **Done.** `organization_requests`, `signup_requests` |
| Settings | `/settings` | **Done.** Profile fields, avatar, chat wallpaper |
| User reports / moderation mail | `POST /api/users/reports/{username}` | **Done.** `reports` table plus an emailed copy to `REPORTS_EMAIL` |
| Media / Cloudinary | `/api/users/me/avatar`, message photos | **Done when configured.** `media` table; upload endpoints return 503 and the UI says so until all three Cloudinary keys are set |

### In flight

Chat pins, wallpapers, in-chat product cards and offers (`app/services/offers.py`,
`app/models/message_extras.py`, `0011_message_extras`, `0012_offers_deal`) are
committed as a `wip:` commit so they cannot be lost, but treat them as **not
built**: `0012` has not been applied to Supabase and there are no tests of their
own. The messaging tests cover the conversations they hang off, not these.

### Operational gaps that are not feature gaps

Listed in full in `REMAINING-WORK.md`; repeated here because they decide whether
"Done" survives contact with production:

1. Migrations `0010`–`0012` are not applied to the Supabase database. The test
   suite builds its schema from `create_all`, so a green run says nothing about
   production.
2. The WebSocket fan-out is a per-process dict. With more than one worker, a
   message sent on worker A does not reach a socket held by worker B — it fails
   quietly, and reconnect-and-refetch hides it.
3. Nothing schedules `purge_expired`, so expired messages are only reclaimed in
   conversations somebody still opens.

**The house rule these all follow:** where a feature has no storage behind it, the UI
says so — an empty state, a "waiting on X" chip, or a toast naming the missing table.
It never renders invented data. That is strictest for anything about a user's money:
no specimen order on `/orders`, and no example revenue figure in the Business Hub.
