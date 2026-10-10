# 08. Profiles

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

Profiles are the identity pages of CartFlow.

Every user has a profile where other users can learn more about them, view their content, interact with them, and discover products or events they offer.

CartFlow supports two profile types:

- Student Profiles
- Business Profiles

Both profile types share a consistent design language while exposing features relevant to each account type.

---

# 2. Objectives

Profiles should:

- Help users build their identity.
- Encourage following and engagement.
- Showcase posts.
- Showcase businesses and products.
- Improve discoverability.
- Make messaging simple.
- Serve as permanent public pages.

---

# 3. Profile URL

Every profile has a permanent shareable URL.

Example:

```
https://cartflow.africa/@berachaiah

https://cartflow.africa/@royalfragrance
```

Profile URLs remain stable unless the username changes.

Old profile URLs should automatically redirect to the new username.

---

# 4. Student Profile Layout

```
Profile Picture

Display Name

@username

University

Bio

Followers • Following

Edit Profile

-----------------------

Posts

Liked

Saved

Reposts

-----------------------

Post Grid
```

---

# 5. Student Profile Components

Every student profile contains:

- Profile picture
- Display name
- Username
- Bio
- University
- Followers count
- Following count
- Posts count

---

# 6. Student Tabs

Students have four content tabs.

## Posts

Displays every post published by the student.

---

## Liked

Displays posts liked by the user.

Visibility:

Only the account owner can see this tab.

---

## Saved

Displays saved posts.

Only visible to the account owner.

---

## Reposts

Displays reposted content.

Shows original author attribution.

---

# 7. Business Profile Layout

```
Business Logo

Business Name

@username

University

Business Category

Business Status

Website

Bio

Followers

Following

Message

Shop

-----------------------

Products

Posts

Events

Reviews

Liked

Saved

Reposts

-----------------------

Content Grid
```

---

# 8. Business Profile Components

Business profiles contain:

- Business logo
- Business name
- Username
- University
- Business category
- Bio
- Website
- Business status
- Followers
- Following
- Shop button
- Message button

---

# 9. Website Links

Businesses may add one website.

Supported examples:

```
https://royalfragrance.com

https://instagram.com/brand

https://wa.me/234...

https://linktr.ee/...
```

Links open externally.

---

# 10. Business Status

Businesses may display one of:

- Open
- Closed
- Holiday Mode
- Temporarily Unavailable

The status is visible throughout the application wherever the business appears.

---

# 11. Products Tab

Displays products belonging to the business.

Each card displays:

- Product image
- Product name
- Price
- Discount badge (if applicable)

Selecting a product opens its Product Details page.

---

# 12. Posts Tab

Displays all feed posts created by the business.

Posts appear in reverse chronological order.

---

# 13. Events Tab

Displays events organized by the business.

Each event card includes:

- Banner
- Event name
- Date
- Ticket status

Selecting a card opens the Event Details page.

---

# 14. Reviews Tab

Displays customer reviews.

Each review contains:

- Customer name
- Rating
- Review text
- Date

Businesses cannot edit customer reviews.

Only administrators may remove reviews that violate platform policies.

---

# 15. Social Actions

Visitors may:

- Follow
- Unfollow
- Message
- Share Profile
- Report Profile

Business profiles additionally expose:

- Shop
- Website

---

# 16. Share Profile

Profiles may be shared internally or externally.

Internal:

- Direct Messages

External:

- Copy Link
- WhatsApp
- Telegram
- Facebook
- X
- Instagram
- System Share Sheet

---

# 17. Followers

Displays users following the account.

Supports:

- Search
- Remove follower (future)
- Follow back

---

# 18. Following

Displays accounts followed by the user.

Supports:

- Search
- Unfollow

---

# 19. Edit Profile

Students may edit:

- Name
- Username
- Bio
- Profile picture
- Address

Businesses may additionally edit:

- Business logo
- Website
- Business status
- Delivery coverage
- Pickup location

---

# 20. Profile Statistics

Visible statistics include:

- Posts
- Followers
- Following

Business profiles additionally display:

- Products
- Events

Detailed analytics remain available only in Business Hub.

---

# 21. Empty States

Examples:

"No posts yet."

"No products available."

"No events created."

"No reviews yet."

Each empty state should guide users toward the next action.

---

# 22. Privacy

Version 1 uses public profiles.

Future versions may introduce:

- Private accounts
- Close Friends
- Hidden follower lists

---

# 23. Reporting

Users may report profiles for:

- Spam
- Fraud
- Harassment
- Impersonation
- Inappropriate content

Reports enter the moderation queue.

---

# 24. Blocking

Blocked users:

- Cannot follow
- Cannot message
- Cannot mention
- Cannot interact with the profile

Blocking is mutual.

---

# 25. Performance

Profile pages should:

- Load incrementally.
- Lazy-load post grids.
- Cache profile metadata.
- Optimize profile images using Cloudinary transformations.

---

# 26. Future Enhancements

Potential future additions:

- Profile verification badges
- Pinned posts
- Story Highlights
- Featured products
- Featured events
- Profile themes
- Creator mode
- Business insights preview

---

# 27. Summary

Profiles are the digital identity of every user and business on CartFlow.

Student profiles emphasize social interaction, while Business profiles extend that experience with commerce, products, events, and customer engagement.

The consistent profile experience helps users move naturally between social networking and shopping while maintaining a unified interface across the platform.

---

# Implementation Status — as built (August 16, 2026)

**Route:** `GET /@{username}` — `app/routers/pages.py:profile` →
`app/templates/profile.html`.
**API:** `app/routers/users.py` — `PATCH /api/users/me`,
`POST|DELETE /api/users/{username}/follow`,
`GET /api/users/{username}/followers`, `GET /api/users/{username}/following`.
Service: `app/services/follow.py` over the `user_follows` table.
**Tests:** `tests/test_follow.py`, `tests/test_profile_page.py`.

This is the first page wired to real data end to end.

**Real:**

- Identity, affiliation and the seller check, from the `users` / `organizations`
  rows. A student who sells keeps their school as `organization`; the shop is a
  separate row they own, fetched only for sellers.
- **Follower / following counts and follow state** — one query, two scalar
  subqueries plus an `exists()` for the viewer. Follow and unfollow are idempotent
  (a double-tapped button must not error); self-follow is a 422.
- The Followers / Following sheets, fetched from the API with a client-side filter
  box (§17-§18). They return `PublicUserOut`, which deliberately omits `email` —
  `tests/test_profile_page.py` asserts the owner's address never reaches the page.
- **Edit profile** — display name + bio, via `PATCH /api/users/me`.
- **Start selling** (`POST /api/auth/business/upgrade`) and the **graduation
  toggle** (`POST /api/auth/graduation`), both own-profile only. This page is the
  only UI either endpoint has.
- **One canonical URL.** Lookup is case-insensitive on `username_normalized`; a
  URL whose casing differs 301s to the stored form (§52). Unknown, soft-deleted
  and suspended handles all render the same 404 page, so no response confirms that
  a hidden account exists.

**Deferred, and why:**

- **`website` and business status (§9/§10)** — neither column exists on
  `organizations`, and both belong in the Business Hub's editor, so they would
  render empty on every profile.
- **Username change** — needs uniqueness handling, `username_normalized`, and
  old-URL redirects per §54.
- **Every content tab is an honest empty state** — there are no
  `posts`/`products`/`events`/`reviews` tables. Liked and Saved render for the
  owner only (§6), also empty.
- **Avatars are initials-drawn** (`partials/avatar.html`) — `profile_image_media_id`
  exists but there is still no Media model, so nothing fetches an image.
- **No graduate/alumni badge**, by product decision, even though the graduation
  toggle lives here.
- Message / Share / Report are client-side (toast, copy-link, share sheet): there
  is no messaging (doc 10) or moderation backend.

---

# End of Document