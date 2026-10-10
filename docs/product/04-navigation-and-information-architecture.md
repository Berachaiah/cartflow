# 04. Navigation and Information Architecture

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

This document defines how users navigate throughout CartFlow.

It specifies:

- Navigation structure
- Screen hierarchy
- Mobile navigation
- Desktop navigation
- Deep linking
- Search entry points
- Navigation behavior
- URL architecture

The objective is to ensure users can reach any destination with minimal friction while maintaining a clean and intuitive interface.

---

# 2. Navigation Philosophy

CartFlow follows five navigation principles.

## Mobile First

The primary navigation experience is designed for smartphones.

Desktop navigation adapts the mobile experience without changing user expectations.

---

## Consistency

Navigation elements should remain in the same locations throughout the application.

Icons, spacing and interactions should never change unexpectedly.

---

## Progressive Disclosure

Only the most frequently used destinations should remain visible.

Advanced features are hidden until required.

---

## Fast Access

Users should reach any major feature within two or three interactions.

---

## Predictability

Every icon should perform the same action everywhere in the application.

---

# 3. Primary Navigation

CartFlow contains the following primary destinations.

- Home
- Discover
- Shop
- Messages
- Cart
- Business Hub (Business Accounts)
- Settings (Desktop)
- Profile

---

# 4. Mobile Navigation

Mobile uses a bottom navigation bar.

```
--------------------------------------------------

🏠     🔍     ➕     💬     🛒

Home Discover Post Messages Cart

--------------------------------------------------
```

Business accounts additionally see:

```
Business Hub
```

accessible from the Profile page or an additional bottom navigation item depending on screen width.

---

# 5. Mobile Navigation Rules

The bottom navigation remains visible on major pages.

Hidden on:

- Authentication
- Checkout
- Full-screen media viewer
- QR Scanner
- Ticket Scanner
- Settings (optional)

---

# 6. Desktop Navigation

Desktop uses a left sidebar.

```
Logo

Home

Discover

Shop

Messages

Cart

Business Hub

Settings

Profile

Create Post (Business)

Dark Mode Toggle
```

The logo always returns users to Home.

---

# 7. Home

Purpose

Primary social feed.

Contains:

Stories

Feed

Post composer (Business)

Suggested users

Suggested businesses

Infinite scrolling feed

---

# 8. Discover

Purpose

Content discovery.

Contains:

Search

Trending

Recommended users

Recommended businesses

Hashtags

Suggested products

Stories

Events

---

# 9. Shop

Purpose

Commerce.

Contains:

Products

Categories

Search

Filters

Discounts

Recommendations

Business cards

Product cards

---

# 10. Messages

Purpose

Private communication.

Contains:

Chats

Message Requests

Search

Unread indicators

Pinned conversations (future)

---

# 11. Cart

Purpose

Purchase management.

Contains:

Products

Delivery selections

Quantity

Checkout

Saved cart

Order summary

---

# 12. Business Hub

Business accounts only.

Contains:

Dashboard

Products

Orders

Inventory

Events

Analytics

Operations

Payouts

Settings

---

# 13. Profile

Student Profile

Posts

Liked

Saved

Reposts

Followers

Following

Settings shortcut

---

Business Profile

Posts

Products

Events

Reviews

Business Status

Shop button

Website

Delivery Coverage

---

# 14. Settings

Accessible from:

Desktop sidebar

Profile page (Mobile)

Contains:

Account

Privacy

Notifications

Business Settings

Payment Settings

Security

Appearance

Support

---

# 15. Secondary Navigation

Examples include:

Product tabs

Business Hub tabs

Settings tabs

Admin tabs

Analytics tabs

These should appear only inside their respective modules.

---

# 16. Navigation Hierarchy

```
Home

├── Stories

├── Feed

├── Post

├── Profile

├── Product

└── Business
```

---

```
Shop

├── Categories

├── Product

├── Business

├── Cart

└── Checkout
```

---

```
Business Hub

├── Dashboard

├── Products

├── Orders

├── Inventory

├── Events

├── Analytics

├── Operations

└── Settings
```

---

# 17. URL Structure

Every public resource has a permanent URL.

Examples

```
/

/discover

/shop

/messages

/cart

/@username

/product/{slug}

/business/{slug}

/event/{slug}

/post/{id}
```

---

# 18. Deep Linking

Users can directly open:

Profiles

Products

Posts

Businesses

Events

Stories (future)

QR Tickets

Shared links always open the appropriate page.

---

# 19. Browser Navigation

Back button should:

Return users to the previous screen.

Never unexpectedly exit multi-step workflows.

Form progress should remain intact where possible.

---

# 20. Search Entry Points

Search exists within:

Discover

Shop

Messages

Business Hub

Admin Panel

Search behaves differently depending on context.

---

# 21. Empty States

Every major page must include an informative empty state.

Examples:

No products.

No messages.

No orders.

No posts.

No events.

Every empty state should guide users toward the next logical action.

---

# 22. Loading States

Pages should display skeleton loaders while content is loading.

Avoid blank white screens.

Loading indicators should closely resemble the final layout.

---

# 23. Error States

If navigation fails:

Display a friendly error message.

Offer:

Retry

Go Back

Return Home

Never expose internal server errors to end users.

---

# 24. Responsive Breakpoints

Mobile

0–767px

Tablet

768–1023px

Desktop

1024px+

Large Desktop

1440px+

Navigation adapts automatically.

---

# 25. Accessibility

Navigation should support:

Keyboard navigation

Screen readers

Visible focus indicators

High contrast

Large touch targets

---

# 26. Future Enhancements

Potential future improvements:

Quick Search Palette

Keyboard shortcuts

Split-screen messaging

Pinned navigation

Workspace switching

Custom navigation ordering

---

# 27. Summary

The CartFlow navigation system is designed to be:

- Simple
- Predictable
- Mobile-first
- Responsive
- Scalable

Every future feature must integrate into this navigation system without increasing unnecessary complexity.

---

# Implementation Status — as built (August 16, 2026)

**Where it lives:** `app/templates/base.html` — every non-`bare` page inherits the
whole chrome from it. Page routes are in `app/routers/pages.py`.
**Tests:** `tests/test_page_render.py`.

**Built:**

- **Desktop sidebar (lg+)** — Home `/`, Discover `/discover`, Shop `/marketplace`,
  Orders `/orders`, Business Hub `/dashboard`, Profile `/@handle`. Plus the theme
  toggle and the identity card, which links to the signed-in user's own profile.
- **Mobile bottom tab bar** — Home · Discover · **+** · Shop · Profile, visible on
  every major page, `pb-[calc(8px+var(--safe-b))]` for the home-indicator inset.
- **Top bar** — an overridable `topbar` block. The default carries the CartFlow
  wordmark (mobile) plus the page title (lg+); Home overrides it with the
  branded bar. Hidden on `bare` pages.
- **Create (+)** — opens `#createSheet`, defined in `base.html` next to the
  buttons. See the deviation note below.
- **`bare` pages** — authentication, password reset, email verification and the
  organization directory render no sidebar, no tab bar and no create sheet, which
  is §5's "hidden on Authentication" rule.

**Deviations from §5/§6, and why:**

- **Settings → Profile.** §6 lists Settings in the sidebar. There is no
  `/settings` route and no settings backend, so the slot goes to Profile — a
  route that exists — and the account actions (edit profile, start selling,
  graduation, log out) live behind the `⋯` button on the profile page. One less
  dead link, and the settings sit next to the identity they change.
- **Messages and Cart are not sidebar items.** Messaging has no backend at all
  (doc 10), and the cart is a sheet on `/marketplace` rather than a page, because
  there is no cart table (doc 13). A sidebar entry for either would be a link to
  nothing.
- **Create is not gated on `is_seller`.** §6 lists it as "Create Post
  (Business)", but there is no `posts` table, so a seller-only composer would be
  a form that drops its input. The button is therefore visible to everyone and
  opens a sheet that offers the create-shaped actions that DO work — creating a
  shop, editing your profile — and names what each deferred one is waiting on.
- Business Hub stays in the desktop sidebar and is reachable on mobile from the
  profile page rather than taking a sixth tab slot.

**Not built:** breadcrumbs, a QR/ticket scanner route (doc 17, Milestone 2), and
the full-screen media viewer as a route (the story viewer is in-page on Home).

---

# End of Document