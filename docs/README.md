# CartFlow Docs

## Source of truth

The **Markdown** files in `product/` and `engineering/` are the authoritative,
current specification. They are kept in sync with the code.

The `.docx` PRD chapters (e.g. `CartFlow_PRD_V1_Chapter_*.docx`) are **frozen
V1 exports for reference only**. They predate the multi-persona auth work
(identity-vs-capability accounts, Individual persona, Google Sign-In,
"Start selling", graduation) and are **known to be out of date**. Do not treat
them as current — when a `.docx` and a `.md` disagree, the `.md` wins.

_Last reconciled with code: August 16, 2026._

## What is built, and where

Each product doc listed below ends with an **"Implementation Status — as built"**
section naming the route, the template, the tests, and — the part that matters most
when picking up work — **what is deferred and why**. Read that section before
building against a chapter: the spec describes V1, not today.

| Doc | Route | Template | Status |
|---|---|---|---|
| 03, 05 — accounts & auth | `/signup`, `/login`, `/forgot-password`, `/reset-password`, `/verify-email` | `signup.html`, `login.html`, … | **Done.** Multi-persona signup, Google Sign-In, sessions, password reset, login lockout |
| 04 — navigation & IA | all | `base.html` | **Done.** Sidebar, bottom tab bar, top bar, create sheet |
| 06 — home feed | `/` | `home.html` | Chrome + captions real; posts are placeholder (no `posts` table) |
| 07 — discover & search | `/discover` | `discover.html` | Page done; search runs client-side (no index) |
| 08 — profiles | `/@handle` | `profile.html` | **Done, real data.** Follows, edit profile, start selling, graduation |
| 09 — stories | — | (rail in `home.html`) | Not built (no `stories`, no media) |
| 10 — messaging | — | — | Not built |
| 11 — activity & notifications | — | — | Not built |
| 12 — shop & products | `/marketplace` | `shop.html` | Front end done; catalogue is a Jinja fixture (no `products` table) |
| 13 — cart & checkout | `/marketplace` | (`#cartSheet`) | Cart is client-side; checkout not built |
| 14 — orders & delivery | `/orders` | `orders.html` | Honest empty history + the doc's rules as reference (no `orders` table) |
| 15 — payments, escrow, payouts | — | — | Not built; escrow is explained, not enforced |
| 16 — business hub | `/dashboard` | `dashboard.html` | **Three states done.** Business profile editing is real; metrics are honest zeros |
| 17 — events & ticketing | — | — | Milestone 2 |

**The house rule these all follow:** where a feature has no storage behind it, the UI
says so — an empty state, a "waiting on X" chip, or a toast naming the missing table.
It never renders invented data. That is strictest for anything about a user's money:
no specimen order on `/orders`, and no example revenue figure in the Business Hub.
