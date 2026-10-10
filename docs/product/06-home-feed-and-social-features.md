# 06. Home Feed and Social Features

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Home Feed is the heart of CartFlow.

It is the first screen users see after logging in and serves as the primary destination for discovering people, businesses, products, events, and campus activities.

Unlike traditional marketplaces, CartFlow is built around social discovery. Commerce should naturally emerge from engaging content rather than isolated product listings.

---

# 2. Objectives

The Home Feed should:

- Encourage daily engagement.
- Help businesses reach customers organically.
- Allow students to express themselves.
- Promote products without feeling like advertisements.
- Surface relevant content through engagement-based ranking.
- Increase interaction between students and businesses.

---

# 3. Feed Layout

The mobile Home Feed consists of:

```
─────────────────────────────

CartFlow Logo

Activity Inbox

Messages

─────────────────────────────

Stories

─────────────────────────────

Infinite Feed

─────────────────────────────
```

Desktop follows a three-column layout:

- Left Sidebar (Navigation)
- Center Feed
- Right Sidebar (Suggestions, Trending, Active Events)

---

# 4. Stories

Stories appear at the top of the Home Feed.

Both Students and Businesses can create stories.

Stories disappear after 24 hours.

Users may:

- View stories
- React using emojis
- Reply privately
- Skip
- Pause
- Move forward/backward

Future versions may support Highlights.

---

# 5. Feed Content Types

The feed may contain:

- Student posts
- Business posts
- Product announcements
- Event announcements
- Reposts
- Shared content

Products themselves do not appear as standalone feed cards. Instead, businesses create posts that may tag one or more products from their Shop.

---

# 6. Post Creation

Students may create:

- Image posts
- Video posts
- Text captions

Businesses may additionally:

- Tag products
- Promote discounts
- Announce events

Posts are created through the universal Create Post screen.

---

# 7. Supported Media

Version 1 supports:

Images

Videos

Maximum image count:

10 per post.

Maximum video count:

1 per post.

Media is stored using Cloudinary.

---

# 8. Caption

Captions support:

- Plain text
- Emojis
- Mentions (@username)
- Product tags
- Event tags
- Hashtags
- Line breaks

Captions have a generous maximum length while encouraging concise content.

---

# 9. Mentions

Users may mention:

Students

Businesses

Mentions become tappable links.

Mentioned users receive notifications.

---

# 10. Product Tagging

Businesses may tag products directly within posts.

Tagged products appear as tappable links within the caption or media overlay.

Selecting a tagged product opens its product page.

A post may reference multiple products.

Product tagging uses an autocomplete field similar to mentioning users.

---

# 11. Event Tagging

Businesses may tag events they manage.

Tagged events open directly to the event details page.

---

# 12. Hashtags

Users may include hashtags in captions.

Examples:

#BellsUniversity

#CampusFashion

#FreshersParty

#Perfume

Hashtags are searchable and contribute to content discovery.

---

# 13. Image Editing

Before publishing, users may:

- Crop images
- Rotate
- Adjust brightness
- Adjust contrast
- Apply basic filters

Advanced photo editing is intentionally excluded from Version 1.

---

# 14. Creative Tools

Users may decorate images before posting.

Supported tools:

- Text
- Stickers
- Drawing
- Emoji placement

These edits become part of the uploaded media.

---

# 15. Music

Users may add audio to:

Stories

Feed videos

Supported sources:

- Original audio
- Licensed music library
- Previously used sounds

Music availability depends on licensing.

---

# 16. Feed Card Layout

Each feed card displays:

Profile image

Username

Business badge (if applicable)

Timestamp

Media

Tagged products

Caption

Like

Comment

Repost

Share

Save

Three-dot menu

Like count

Comment count

---

# 17. Social Interactions

Users may:

Like

Comment

Save

Share

Repost

Report

Hide

Follow

Visit profile

---

# 18. Comments

Comments support:

Replies

Mentions

Emojis

Likes

Comment threads remain collapsed until expanded.

---

# 19. Reposts

Users may repost another user's content.

Reposts retain attribution to the original creator.

The original post remains the canonical version.

---

# 20. Saves

Saved posts are private.

Users access saved posts from their profile.

Businesses also have access to saved posts.

---

# 21. Likes

Users may like and unlike posts.

Businesses may also like posts.

Like counts update in real time.

---

# 22. Shares

Two sharing methods exist.

## Internal Share

Send to:

Individual chats

Group chats (future)

Shared posts retain their original source.

---

## External Share

Available through the three-dot menu.

Supports:

Copy Link

WhatsApp

Instagram

X

Facebook

Telegram

System share sheet

---

# 23. Three-Dot Menu

Options include:

Copy Link

Share

Report

Hide

Not Interested

Delete (own posts)

Edit (own posts)

---

# 24. Feed Ranking

The Home Feed prioritizes:

Posts from followed accounts

↓

High engagement posts

↓

Recommended content

↓

Nearby businesses

↓

Recent content

↓

Older content

Machine learning may improve ranking in future versions.

---

# 25. Infinite Scrolling

The Home Feed uses infinite scrolling.

Older posts load automatically.

Pagination remains server-driven.

---

# 26. Activity Inbox

Users receive notifications for:

New followers

Likes

Comments

Mentions

Replies

Reposts

Order updates

Event updates

Businesses additionally receive:

New orders

Product reviews

Inventory alerts

---

# 27. Reporting

Posts may be reported for:

Spam

Harassment

Fraud

Illegal content

Copyright

Reports enter the moderation queue.

---

# 28. Privacy

Users may delete their own posts.

Businesses may delete promotional posts.

Deleted posts are soft-deleted and recoverable for a limited period.

---

# 29. Analytics

Businesses can view:

Post impressions

Reach

Likes

Comments

Shares

Saves

Profile visits

Product clicks

Event clicks

Students do not receive detailed analytics in Version 1.

---

# 30. Future Enhancements

Potential future additions:

Polls

Collaborative posts

Pinned posts

Scheduled publishing

Carousel templates

Story Highlights

AI caption suggestions

Creator analytics

---

# 31. Summary

The Home Feed is designed to make social interaction the primary driver of commerce within CartFlow.

Students engage naturally with content while businesses showcase products, services, and events in a way that feels authentic rather than promotional.

This balance between social interaction and commerce forms the foundation of the CartFlow experience.

---

# Implementation Status — as built (August 18, 2026)

**Route:** `GET /` — `app/routers/pages.py:home` → `app/templates/home.html`.
**Tests:** `tests/test_page_render.py`, `tests/test_feed_media.py`,
`tests/test_name_display.py`.

**Real (backed by data):**

- The signed-in identity in the chrome and in the right rail — display name,
  `@handle`, seller check, organization affiliation — from
  `get_current_user_optional`. Signed out renders a log-in state, never a 401.
- **Caption rendering.** `_caption_html` in `app/routers/pages.py` turns
  `#hashtags` into `/discover?tag=` links and `@mentions` into `/@handle` links,
  HTML-escaping everything between them. It runs on the RAW caption so an escaped
  apostrophe (`&#39;`) can never be mis-tokenised as `#39`. Emoji are swapped to
  Twemoji client-side (`window.cfParseEmoji`).
- "Start selling" in the right rail links to the real form (`/dashboard`), since
  `POST /api/auth/business/upgrade` has shipped.

**Placeholder (no backend exists):** the posts themselves, the stories rail, the
comment counts, the like/save/repost counters. There is no `posts`, `stories`,
`media`, `likes`, `saves` or `comments` table, so the feed is a curated Jinja list
defined at the top of the template, shaped so a future feed response drops in
without changing the markup. Like and save are client-side only — the count moves
and the state sticks for the session, nothing is written — and the placeholder
handles (`retrovibe`, `sneakerlab`, …) are deliberately NOT linked to `/@handle`:
they have no `users` rows, so every link would 404. `cfInitPostMedia(node)` is a
function rather than inline script for the same reason: whatever eventually
replaces `feed_posts` can call it on what it injects.

**Not built:** the composer (§4-7). The `+` button opens the create sheet in
`base.html`, which names Post as waiting on `posts` + `media` rather than opening
a form that would drop the caption and the image on submit. Comments, reposts and
the activity inbox (doc 11) are all unbuilt for the same reason.

**Post interaction — real, and needs no backend (August 18, 2026):**

- **Multi-photo posts are a carousel.** They were a `grid grid-cols-3` over
  `post.media[:3]`: every photo at once, each squashed to a third of the width,
  and anything past the third silently dropped — a five-photo post rendered as
  three thumbnails with two photos nobody could reach. Now one photo at a time in
  a native CSS scroll-snap track (`flex overflow-x-auto snap-x snap-mandatory`,
  slides `snap-center shrink-0 w-full`), with an IG-style `n/N` counter top-right
  and dots bottom-centre. No touch handlers: momentum, rubber-banding, trackpad
  and wheel scrolling come free from the browser, and it degrades to a plain
  scroller with JS off. `overscroll-behavior-x: contain` stops a swipe past the
  last photo from becoming the browser's back gesture. JS only *reads*
  `scrollLeft`, to move the counter and dots.
- **Double-tap to like.** Counted from `pointerdown`/`pointermove`/`pointerup`
  rather than `dblclick`, so one code path serves finger, mouse and trackpad —
  and so a gesture that travelled more than 12px can be vetoed as a swipe, which
  `dblclick` gives no hook for. Without that veto, flicking through a carousel
  liked the post every couple of photos. `pointercancel` resets the counter,
  because a pan hands the pointer to the scroller and never fires `pointerup`.
  **The gesture only ever likes, never un-likes** — it is easy to fire by
  accident, and silently removing a like is the one outcome you cannot see
  happen. The heart bursts either way, so it always feels like it registered;
  the animation is suppressed under `prefers-reduced-motion`.
- **One definition of "liked".** There are two ways to like a post now, so both
  the heart button and the gesture go through `setLiked()`. A feed where the two
  disagree about the count is worse than having only one of them.
- **Sharing opens real services.** The sheet showed Material Symbols standing in
  for the brands — `chat` for WhatsApp, `photo_camera` for Instagram, `tag` for
  X, `thumb_up` for Facebook — and every button toasted "Shared to …" without
  opening anything. It now carries the genuine marks (`app/templates/partials/
  brand_icons.html`; path data from Simple Icons, CC0 1.0, the marks themselves
  their owners' trademarks used nominatively to label the button that shares to
  that service). WhatsApp, X and Facebook open their real web share intents,
  every `window.open` carrying `noopener,noreferrer`. Instagram and Message copy
  the link and say so: Instagram publishes no web share endpoint at all, and
  CartFlow messaging has no compose-with-attachment (doc 10).
- **Names are not clipped.** `truncate` on a name turned "SneakerLab" into
  "Sneaker …", which is not an abbreviation — it is a different shop. Names wrap
  or clamp to two lines; the `@handle · 2h · Bells University` line below still
  truncates, because that genuinely is abbreviatable. Same split Instagram uses.
  The rule and its allowlist of fixed-string exceptions live in
  `tests/test_name_display.py`.

---

# End of Document