# 18. Recommendation and Ranking

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Recommendation and Ranking system determines the order in which content is displayed throughout CartFlow.

Its goal is to maximize relevance, engagement, and discovery while giving new businesses and creators a fair opportunity to reach users.

Unlike traditional chronological feeds, CartFlow uses a scoring-based ranking algorithm.

---

# 2. Objectives

The recommendation engine should:

- Personalize content.
- Promote relevant businesses.
- Increase product discovery.
- Increase event visibility.
- Reward quality content.
- Prevent spam.
- Support future machine learning integration.

---

# 3. Ranking Philosophy

Every feed inside CartFlow has its own ranking system.

They are:

- Home Feed
- Discover
- Shop
- Search
- Stories

Each uses different ranking signals.

---

# 4. Home Feed Ranking

The Home Feed contains:

- Posts from followed accounts
- Recommended posts
- Business posts
- Event posts
- Reposts

Products themselves do not appear in the Home Feed unless tagged inside a post.

---

# 5. Home Feed Signals

Posts receive a ranking score based on:

- Following relationship
- Recent engagement
- Likes
- Comments
- Shares
- Saves
- Reposts
- Profile visits
- Post freshness
- University relevance

Example weights:

Following: +50

Comment: +20

Share: +25

Save: +18

Like: +10

Recent post: +15

These values are configurable.

---

# 6. Discover Ranking

Discover focuses on exploration.

Signals include:

- Trending posts
- Popular creators
- Nearby businesses
- Similar interests
- Recently growing accounts

Following status has less influence than in the Home Feed.

---

# 7. Shop Ranking

The Shop uses a commerce-focused ranking.

Signals include:

- Purchases
- Add-to-cart rate
- Saves
- Product views
- Conversion rate
- Reviews
- Ratings
- Inventory availability
- Discounts
- Product freshness

Products with repeated poor reviews are ranked lower.

---

# 8. Story Ranking

Stories appear in a horizontal list.

Ranking considers:

- Frequent interactions
- Messages
- Profile visits
- Story views
- Replies
- Following relationship

Stories disappear after 24 hours.

---

# 9. Search Ranking

Search considers:

- Username match
- Business name
- Product name
- Event name
- Popularity
- Exact matches
- Recent engagement

Exact matches receive the highest priority.

---

# 10. Event Ranking

Events are treated as regular posts.

Their visibility depends on:

- Engagement
- Shares
- Saves
- Comments
- Ticket purchases
- Event date proximity

Upcoming events receive a temporary ranking boost.

---

# 11. Product Recommendations

Recommendations on Product pages use:

- Same category
- Similar price
- Same business
- Frequently viewed together
- Frequently purchased together

---

# 12. University Relevance

Content from the user's selected university receives a ranking boost.

However, users can still discover businesses and events from outside their university.

---

# 13. Business Quality Signals

Businesses gain ranking improvements from:

- High ratings
- Fast response time
- Successful deliveries
- Active posting
- High customer satisfaction

Repeated disputes reduce ranking.

---

# 14. Freshness

New content receives a temporary boost.

The boost gradually decreases over time.

This prevents older content from permanently dominating feeds.

---

# 15. Diversity

The recommendation engine avoids showing:

- Too many posts from one account.
- Too many products from one business.
- Duplicate content.

This keeps feeds balanced.

---

# 16. Spam Protection

The engine detects:

- Repeated identical posts
- Artificial engagement
- Excessive reposting
- Fake interactions

Spam content is ranked lower.

---

# 17. Cold Start

New businesses receive temporary visibility boosts.

This helps new businesses gain their first customers without needing existing popularity.

---

# 18. Trending

Trending is calculated using:

- Engagement velocity
- Shares
- Saves
- Comments
- Recent growth

Older viral posts naturally lose priority.

---

# 19. Personalization

The recommendation engine learns from:

- Likes
- Saves
- Shares
- Purchases
- Product views
- Story views
- Search history
- Profile visits

Version 1 stores these interactions for future ML enhancements.

---

# 20. Product Tags

Businesses may tag products inside feed posts.

Example:

```
Luxury Perfume

₦8,000
```

Tapping a tagged product opens its Product Details page.

Multiple products may be tagged in one post.

---

# 21. Recommendation Transparency

Users can request:

```
Why am I seeing this?
```

Possible explanations include:

- You follow this business.
- Popular at your university.
- Trending this week.
- Similar to products you've viewed.
- People you follow engaged with this post.

---

# 22. Database Entities

Primary tables:

- user_interactions
- recommendation_scores
- trending_scores
- product_views
- search_history
- feed_impressions

---

# 23. API Endpoints

GET /api/feed

GET /api/discover

GET /api/shop/recommended

GET /api/stories

GET /api/recommendations/products

GET /api/recommendations/events

---

# 24. Performance

The recommendation engine should:

- Cache ranking scores.
- Pre-compute trending content.
- Update recommendations regularly.
- Minimize database queries.

Background jobs calculate ranking scores.

---

# 25. Future Enhancements

Future versions may include:

- MLFlow recommendation models
- Personalized embeddings
- Collaborative filtering
- Content similarity models
- Real-time recommendation updates
- AI-powered interest prediction

---

# 26. Summary

The Recommendation and Ranking system ensures that every section of CartFlow surfaces relevant, engaging, and trustworthy content.

By combining social engagement, commerce signals, freshness, and user behavior into transparent scoring models, Version 1 delivers personalized experiences while laying the foundation for future machine learning enhancements.

---

# End of Document