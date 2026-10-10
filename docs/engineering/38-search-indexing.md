# 38. Search & Indexing

> Version: V1.0
>
> Status: Engineering Documentation
>
> Last Updated: August 2026

---

# 1. Purpose

This document defines the search architecture and indexing strategy for CartFlow.

The objectives are to:

- Deliver fast and relevant search results.
- Support platform growth.
- Keep indexing independent of the storage engine.
- Provide a consistent search experience across the application.

---

# 2. Search Philosophy

Search should be:

- Fast
- Relevant
- Predictable
- Fault tolerant
- Scalable

Search should help users discover content rather than simply matching text.

---

# 3. Searchable Resources

Version 1 supports searching:

- Users
- Businesses
- Products
- Categories
- Events

Future versions may include:

- Feed Posts
- Comments
- Stories
- Universities
- Collections
- Tags

---

# 4. Global Search

Global Search combines results from multiple resource types.

Example search:

```
water bottle
```

May return:

- Products
- Businesses
- Categories
- Events

Results are grouped by resource type.

---

# 5. Search Entry Points

Search is available from:

- Discover
- Shop
- Business Directory
- Event Directory
- User Search

Each page may apply its own filters.

---

# 6. Product Search

Products are indexed by:

- Name
- Description
- Category
- Brand (future)
- Tags
- Keywords

---

# 7. Business Search

Businesses are indexed by:

- Business Name
- Username
- Bio
- Category
- Delivery Coverage
- Pickup Availability

Business status (Open, Closed, On Holiday) does not affect discoverability but may be displayed in results.

---

# 8. User Search

Users are indexed by:

- Username
- Display Name

Private account information is never indexed.

---

# 9. Event Search

Events are indexed by:

- Title
- Description
- Location
- Organizer
- Category (future)

Expired events are removed from active search results.

---

# 10. Category Search

Categories support:

- Exact matches
- Partial matches

Categories are centrally managed.

---

# 11. Search Ranking

Ranking considers:

- Text relevance
- Popularity
- Freshness
- Engagement
- Availability (where applicable)

Ranking formulas may differ by resource type.

---

# 12. Product Ranking

Products may be ranked by:

- Relevance
- Sales
- Likes
- Saves
- Recent activity
- Inventory availability

Sponsored products (future) follow separate ranking rules.

---

# 13. Business Ranking

Businesses may be ranked by:

- Relevance
- Followers
- Product engagement
- Recent activity
- Customer reviews
- Active status

---

# 14. Event Ranking

Events may be ranked by:

- Relevance
- Ticket sales
- Engagement
- Event date proximity

Past events are excluded from default search results.

---

# 15. Autocomplete

Autocomplete should support:

- Products
- Businesses
- Usernames
- Categories
- Events

Suggestions appear while typing.

---

# 16. Search Suggestions

Suggestions may include:

- Popular Searches
- Recent Searches
- Trending Products
- Trending Businesses

Recent searches are private to each user.

---

# 17. Search Filters

Product filters:

- Category
- Price Range
- Availability
- Discounted Products

Business filters:

- Delivery Coverage
- Pickup Available
- Seller Delivery Available

Event filters:

- Upcoming
- Free
- Paid

---

# 18. Sorting

Supported sort options include:

Products

- Relevance
- Newest
- Price: Low to High
- Price: High to Low
- Most Popular

Businesses

- Relevance
- Most Followed
- Most Active

Events

- Soonest
- Most Popular
- Newest

---

# 19. Search Index Updates

Indexes should update when:

- A resource is created.
- A searchable field changes.
- A resource is deleted.
- A resource becomes inactive.

Updates should occur asynchronously where practical.

---

# 20. Search Performance

Target response time:

< 300 milliseconds

Frequently searched content may be cached.

---

# 21. Search Analytics

Track:

- Search volume
- Zero-result searches
- Popular queries
- Click-through rate
- Search abandonment

These metrics help improve search quality.

---

# 22. Privacy

Search must never expose:

- Email addresses
- Phone numbers
- Hidden profile fields
- Internal identifiers

Only public information is searchable.

---

# 23. Future Enhancements

Potential additions:

- Fuzzy Search
- Typo Tolerance
- Synonyms
- Natural Language Search
- Voice Search
- AI-assisted Search
- Semantic Search

---

# 24. Recommendation

The search architecture should remain independent of any specific search engine.

The application should communicate with a Search Service rather than directly with PostgreSQL Full-Text Search, Meilisearch, Elasticsearch, or another provider. This abstraction allows the underlying search technology to be replaced in the future without affecting business logic or API contracts.

Additionally, search ranking algorithms should be configurable rather than hard-coded, making it easier to improve relevance as user behavior evolves.

---

# 25. Summary

CartFlow's search system is designed to provide fast, relevant, and scalable discovery across users, businesses, products, categories, and events.

By separating indexing, ranking, and presentation concerns, the platform remains flexible enough to evolve from a simple database-backed search in Version 1 to more advanced search technologies in future releases while maintaining a consistent user experience.

---

# End of Document