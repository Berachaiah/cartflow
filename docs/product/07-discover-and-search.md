# 07. Discover and Search

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Discover page enables users to explore content beyond the people and businesses they already follow.

Unlike the Home Feed, which prioritizes content from followed accounts and personalized recommendations, Discover focuses on helping users find new people, businesses, products, events, and trending content.

Discover is one of the primary growth mechanisms of CartFlow.

---

# 2. Objectives

The Discover experience should:

- Help users discover new businesses.
- Help students discover other students.
- Increase product visibility.
- Surface trending content.
- Promote active events.
- Encourage profile exploration.
- Support powerful search across the platform.

---

# 3. Entry Points

Users can access Discover by:

- Bottom Navigation (Mobile)
- Sidebar Navigation (Desktop)

The search bar is integrated into the Discover page.

There is no standalone Search page.

---

# 4. Page Layout

Mobile Layout

```
──────────────────────────

Search Bar

──────────────────────────

Trending Searches

──────────────────────────

Suggested Users

──────────────────────────

Suggested Businesses

──────────────────────────

Trending Posts

──────────────────────────

Trending Products

──────────────────────────

Upcoming Events

──────────────────────────
```

Desktop follows the same structure with a wider responsive layout.

---

# 5. Universal Search

The search bar searches across multiple content types simultaneously.

Supported search targets:

- Students
- Businesses
- Products
- Events
- Hashtags

Search results are grouped by category.

---

# 6. Search Behavior

Search begins after the user enters one or more characters.

Results update dynamically as the user types.

Search supports:

- Partial matches
- Prefix matches
- Username matches
- Product name matches
- Business name matches

---

# 7. Search Result Categories

Search results appear under separate sections.

## Users

Displays:

- Profile photo
- Name
- Username
- University

Selecting a result opens the user's profile.

---

## Businesses

Displays:

- Business logo
- Business name
- Username
- Business category
- University

Selecting a result opens the business profile.

---

## Products

Displays:

- Product image
- Product name
- Price
- Business name

Selecting a product opens the Product Details page.

---

## Events

Displays:

- Event banner
- Event name
- Organizer
- Date
- Ticket availability

Selecting an event opens the Event Details page.

---

## Hashtags

Displays:

- Hashtag
- Number of posts

Selecting a hashtag opens a dedicated hashtag page.

---

# 8. Trending Searches

The Discover page displays currently popular searches.

Examples:

- #FreshersWeek
- Perfumes
- Hoodies
- BUSA Dinner
- Power Bank

Trending searches update automatically.

---

# 9. Suggested Users

Suggested users are based on:

- Same university
- Mutual followers
- Shared interests (future)
- Recent interactions

Suggestions are refreshed periodically.

---

# 10. Suggested Businesses

Businesses may be recommended based on:

- University
- Popularity
- Engagement
- Recent activity
- Categories users interact with

---

# 11. Trending Posts

Trending posts are selected using engagement signals such as:

- Likes
- Comments
- Shares
- Saves
- Reposts
- Recency

Trending posts are not restricted to followed accounts.

---

# 12. Trending Products

Trending products are based on:

- Purchases
- Product views
- Saves
- Add-to-cart actions
- Recent popularity

Trending products encourage discovery without relying solely on advertising.

---

# 13. Upcoming Events

The Discover page surfaces active and upcoming events.

Events may be prioritized by:

- Date
- Ticket sales
- Popularity
- User's university

Expired events are excluded.

---

# 14. Search Filters

Different result types provide different filters.

Product filters:

- Category
- Price
- Discount
- Availability

Event filters:

- Date
- Free/Paid
- University

User filters:

- University

Business filters:

- Category
- University

---

# 15. Search History

Users may view their recent searches.

History includes:

- Users
- Businesses
- Products
- Events
- Hashtags

Users can:

- Remove individual entries
- Clear all history

Search history is private.

---

# 16. Search Suggestions

As users type, suggested completions may appear.

Suggestions can include:

- Usernames
- Business names
- Product names
- Events
- Hashtags

---

# 17. No Results

When no results are found:

Display a friendly message.

Provide suggestions such as:

- Check spelling.
- Try another keyword.
- Browse trending content.

---

# 18. Search Ranking

Search results prioritize:

Exact matches

↓

Prefix matches

↓

Popularity

↓

Recent activity

↓

Partial matches

Business names and usernames should rank highly when they closely match the query.

---

# 19. Deep Linking

Every searchable resource has a permanent URL.

Examples:

```
/@username

/product/{slug}

/business/{slug}

/event/{slug}

/hashtag/{tag}
```

Shared links always open the correct resource.

---

# 20. Performance

Search should remain responsive even with large datasets.

Recommended implementation:

- Database indexes on searchable fields.
- Debounced client-side requests.
- Server-side pagination.
- Cached popular searches.

---

# 21. Privacy

Private content (future feature) should never appear in search results unless the user has permission to view it.

Blocked users should not appear in each other's search results where appropriate.

---

# 22. Analytics

Track:

- Most searched keywords
- Search success rate
- Search abandonment
- Most viewed profiles
- Most viewed products
- Most viewed businesses
- Most viewed events

These analytics help improve recommendations and discoverability.

---

# 23. Future Enhancements

Potential future additions:

- Voice Search
- Visual Search
- AI-powered recommendations
- Personalized search ranking
- Search by image
- Saved searches
- Advanced filters

---

# 24. Summary

The Discover page serves as CartFlow's exploration hub, connecting users with new people, businesses, products, and events.

By combining intelligent search, trending content, and personalized recommendations, Discover supports user engagement while helping businesses and creators grow organically.

---

# Implementation Status — as built (August 16, 2026)

**Route:** `GET /discover` — `app/routers/pages.py:discover` →
`app/templates/discover.html`.
**Tests:** `tests/test_page_render.py`.

**Built:** the universal search box (`#discoverSearch`), the results region
(`#discoverResults`), and every §4 explore section in order — Trending searches,
Suggested students, Suggested businesses, Trending posts, Trending products,
Upcoming events.

**Query params.** The feed already links here, so the page accepts both:
`?q=` (the home search and `@mentions`) and `?tag=CampusWear` (a hashtag from a
caption, re-rendered with its `#` sigil so the client ranks hashtags first). They
collapse into one `initial_query` the box is prefilled with. Both are length-capped
in the route and only ever land in an HTML attribute — Jinja escapes them, and
`tests/test_page_render.py::test_discover_query_is_escaped_not_injected` pins that.

**Deferred — the search itself.** There is no search backend and no index (see
`docs/engineering/38-search-indexing.md`), so matching runs client-side over the
placeholder content rendered into the page. The ranking rules in §7-§10 are
therefore specified but not implemented, and the suggested-accounts rows are
curated fixtures with no `users` rows behind them, which is why they don't link to
`/@handle`. Recommendations (doc 18) are not built at all.

---

# End of Document