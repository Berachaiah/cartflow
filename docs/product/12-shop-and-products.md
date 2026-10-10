# 12. Shop and Products

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Shop is CartFlow's marketplace.

It allows businesses to showcase products while allowing students and other businesses to discover, save, and purchase products.

Unlike traditional e-commerce platforms, products gain visibility through both the Shop and the social feed.

---

# 2. Objectives

The Shop should:

- Make product discovery effortless.
- Encourage impulse purchases.
- Integrate naturally with social content.
- Support business inventory.
- Support discounts.
- Increase conversions.

---

# 3. Shop Layout

Mobile

```
────────────────────────

Search

Categories

Filters

────────────────────────

Recommended Products

Trending Products

Discounts

Newest Products

────────────────────────

Infinite Product Grid

────────────────────────
```

Desktop

Left

- Categories
- Filters

Center

- Product Grid

Right

- Trending
- Recommended
- Active Discounts

---

# 4. Product Card

Every product card displays:

- Product Image
- Product Name
- Price
- Discount Badge (if applicable)
- Business Name
- Average Rating
- Number of Reviews

Selecting a card opens the Product Details page.

---

# 5. Product Details Page

Displays:

- Product Images
- Product Name
- Price
- Discount
- Business
- Rating
- Reviews
- Description
- Delivery Coverage
- Quantity Available
- Related Products

Actions:

- Add to Cart
- Save Product
- Share Product
- Visit Business

---

# 6. Product Information

Required fields:

- Name
- Description
- Price
- Quantity
- Category
- Images

Optional:

- Discount
- SKU
- Tags

---

# 7. Product Categories

Examples:

- Fashion
- Electronics
- Beauty
- Food
- Accessories
- Stationery
- Books
- Health
- Sports
- Services (future)

Administrators manage categories.

---

# 8. Product Images

Businesses may upload:

Maximum:

10 images.

Images are optimized automatically through Cloudinary.

---

# 9. Product Search

Products are searchable by:

- Name
- Tags
- Business
- Category

Search supports partial matching.

---

# 10. Filters

Users may filter by:

- Category
- Price
- Discount
- Rating
- Availability
- University
- Delivery Coverage

Filters are sticky until cleared.

---

# 11. Sorting

Products can be sorted by:

- Recommended
- Newest
- Price (Low → High)
- Price (High → Low)
- Best Rated
- Most Purchased
- Biggest Discount

---

# 12. Discounts

Businesses may create discounts.

Discounts display:

Original Price

↓

Discount %

↓

New Price

Discounts automatically expire.

Expired discounts revert to the original price.

---

# 13. Product Availability

Products display:

- In Stock
- Low Stock
- Out of Stock

Out-of-stock products cannot be added to the cart.

---

# 14. Inventory Synchronization

Every successful purchase automatically updates inventory.

Inventory decreases immediately after successful payment.

Businesses can manually restock products through Business Hub.

---

# 15. Delivery Coverage

Businesses specify where they deliver.

Examples:

- Bells University
- Ota
- Ogun State
- Lagos
- Nationwide

Customers can view delivery coverage before adding products to their cart.

---

# 16. Pickup

Businesses configure pickup locations separately.

Pickup locations remain editable.

Customers see pickup addresses during checkout if Pickup is available.

---

# 17. Product Reviews

Only verified buyers may review products.

Each review includes:

- Rating
- Review
- Purchase verification
- Date

Businesses cannot edit reviews.

---

# 18. Product Ratings

Average rating is calculated automatically.

Ratings update after each verified review.

---

# 19. Save Product

Users may save products.

Saved products appear in:

Profile

↓

Saved Products

Only the account owner can view saved products.

---

# 20. Share Product

Products support:

Internal Sharing

- Direct Messages

External Sharing

- Copy Link
- WhatsApp
- Telegram
- Facebook
- X
- Instagram
- System Share Sheet

Every product has a permanent shareable URL.

---

# 21. Related Products

The Product Details page displays similar products.

Recommendations consider:

- Category
- Price
- Business
- User activity

---

# 22. Product Visibility

Products appear in:

- Shop
- Business Profile
- Tagged Feed Posts
- Search
- Recommendations

Products do not appear directly in the Home Feed unless tagged within a feed post.

---

# 23. Reporting

Products may be reported for:

- Fraud
- Counterfeit
- Inappropriate Content
- Incorrect Information
- Spam

Reported products enter moderation.

---

# 24. Analytics

Businesses can view:

- Product Views
- Saves
- Shares
- Add-to-Cart Count
- Purchases
- Conversion Rate
- Revenue
- Inventory Movement

Analytics are available through Business Hub.

---

# 25. Database Entities

Primary tables:

- products
- product_images
- product_categories
- product_tags
- discounts
- product_reviews
- product_views
- product_saves

---

# 26. API Endpoints

GET /api/products

GET /api/products/{slug}

POST /api/products

PUT /api/products/{id}

DELETE /api/products/{id}

GET /api/products/search

POST /api/products/save

POST /api/products/share

POST /api/products/report

---

# 27. Performance

Products should:

- Lazy-load images.
- Cache categories.
- Cache recommendations.
- Optimize thumbnails using Cloudinary.

Pagination remains server-driven.

---

# 28. Future Enhancements

Potential future additions:

- Product Variants (Size, Color)
- Bundles
- Digital Products
- Subscription Products
- Flash Sales
- AI Product Recommendations
- Barcode Scanning
- Price History

---

# 29. Summary

The Shop is CartFlow's commerce engine.

It blends product discovery with social engagement, enabling businesses to reach customers organically while providing students with a familiar and enjoyable shopping experience.

By integrating products into posts, profiles, recommendations, and search, CartFlow creates a commerce experience that feels social rather than transactional.

---

# Implementation Status — as built (August 16, 2026)

**Route:** `GET /marketplace` — `app/routers/pages.py:marketplace` →
`app/templates/shop.html`. Titled **"Shop"** in the UI (sidebar, bottom tab, page
title); the `/marketplace` path stays as-is so existing links keep working.
**Tests:** `tests/test_page_render.py`.

**Built (front end, browsable with no session):** the universal product search
(`#shopSearch`), category chips, the product grid (`#productGrid`), sort (§11),
filters (§10), a no-match empty state (`#gridEmpty`), the product quick-view, and
the cart as a sheet (`#cartSheet`) persisted in `localStorage` under
`cartflow-cart`.

**The catalogue is a curated Jinja `set` at the top of the template**, shaped like
the `GET /api/products` response §26 describes. There is no `products` table, so
those cards ARE the source of truth that the client-side search, sort, filter and
cart read from — the route takes no `db` dependency at all. When the table lands,
the products arrive through the route context and the markup does not change.

**Deferred, and why:**

- **No `products` / `product_variants` / `product_images` / `inventory` tables**, so
  nothing in §5-§9 (create, edit, variants, stock, discounts) is implemented. The
  Business Hub's Products panel is an honest empty state, and the `+` create sheet
  lists Product as waiting on `products`.
- **Search and sort run in the browser** over the rendered cards — there is no
  search backend (`docs/engineering/38-search-indexing.md`).
- **Reviews and ratings** need `reviews`; the stars shown on a card belong to the
  placeholder data.
- **Checkout** is doc 13, and equally unbuilt: adding to the cart works, paying
  does not.

---

# End of Document