# 37. Business Rules

> Version: V1.0
>
> Status: Engineering Documentation
>
> Last Updated: August 2026

---

# 1. Purpose

This document defines the business rules governing CartFlow.

Business rules describe **how the platform behaves**, independent of implementation details. Every backend service, API, and user interface should enforce these rules consistently.

---

# 2. Guiding Principles

Business rules should:

- Be deterministic.
- Be enforceable by the backend.
- Never rely solely on client-side validation.
- Remain independent of UI implementation.
- Be documented before implementation.

---

# 3. User Rules

## Registration

- Email addresses must be unique.
- Usernames must be unique.
- Users must verify their email before accessing protected features.
- A user may own at most one student account.
- A business account is created separately through the Business Hub.

---

## Authentication

- Login requires a verified account.
- JWT access tokens expire after the configured duration.
- Refresh tokens may only generate new access tokens.
- Password reset links expire automatically.

---

# 4. Profile Rules

Users may:

- Edit their profile.
- Change profile picture.
- Update bio.
- Add social links (future).
- Add website links (businesses only).

Businesses may include website URLs in their bio.

---

# 5. Follow Rules

Users may follow:

- Students
- Businesses

Businesses may also follow:

- Students
- Businesses

Following does not require mutual approval.

Blocking overrides following.

---

# 6. Messaging Rules

Users may send an initial message request.

After the recipient:

- Accepts the request,
- Replies,
- or otherwise opens the conversation,

normal messaging becomes available.

Following back is **not required**.

Businesses follow the same messaging rules.

Only image attachments are supported in Version 1.

Video messaging is excluded.

---

# 7. Feed Rules

Posts may contain:

- Text
- Images
- Tagged Products
- Event References

Video posts are not supported in Version 1.

Posts may be:

- Liked
- Commented
- Reposted
- Shared
- Saved

Posts receive permanent URLs.

---

# 8. Story Rules

Stories:

- Expire after 24 hours.
- Support images only.
- Can receive reactions (if enabled).
- Cannot be edited after publishing.
- Are permanently deleted after expiration unless archived in future versions.

---

# 9. Product Rules

Products belong to exactly one business.

Each product:

- Has inventory.
- Has pricing.
- May have discounts.
- May have multiple images.
- May be tagged in feed posts.

Unavailable products cannot be purchased.

---

# 10. Cart Rules

A customer may add products from multiple businesses.

Each cart item stores:

- Quantity
- Selected delivery option

Delivery options are chosen in the cart before checkout.

Changing delivery options updates the cart item.

---

# 11. Delivery Rules

Businesses configure:

- Pickup availability
- Seller delivery availability

Customers choose one enabled option.

Businesses define:

- Pickup location
- Delivery coverage

Customers see delivery coverage before adding to cart.

Customers enter delivery addresses during checkout.

---

# 12. Pickup Rules

Pickup locations:

- Are managed by businesses.
- May change at any time.
- Are independent of university locations.
- Must be visible before checkout.

---

# 13. Seller Delivery Rules

Businesses define where they deliver.

Examples:

- Campus
- Nearby Towns
- Entire State
- Nationwide

Delivery coverage is informational and does not calculate delivery fees.

---

# 14. Order Rules

Orders are created only after successful payment.

Orders cannot be edited after payment.

Order cancellation follows platform policy.

Orders belong to exactly one business.

---

# 15. Payment Rules

Payments:

- Must be verified.
- Create escrow.
- Cannot be manually marked as successful.
- Generate receipts.
- Trigger order creation.

---

# 16. Escrow Rules

Customer payment enters escrow immediately after verification.

Business receives notification immediately.

Funds remain locked until:

Customer confirms delivery

OR

Automatic release occurs.

---

## Automatic Release

If:

- Business confirms delivery

AND

Customer does not respond

Funds release automatically after:

**72 hours**

---

## Manual Release

Administrators may manually release escrow only under exceptional circumstances.

Every manual release generates:

- Audit log
- Administrator record
- Timestamp
- Reason

---

# 17. Refund Rules

Refunds may occur:

- Before delivery
- During disputes
- After administrator approval

Refund policies depend on order status.

---

# 18. Event Rules

Events belong to businesses.

Each event may define:

- Capacity
- Ticket price
- Date
- Location

Each ticket generates one unique QR code.

Duplicate QR scans are rejected.

---

# 19. Business Rules

Businesses may:

- Publish products
- Publish posts
- Publish stories
- Create events
- Receive orders
- Update current location

Businesses can temporarily mark themselves:

- Open
- Closed
- On Holiday

---

# 20. Search Rules

Search indexes:

- Users
- Businesses
- Products
- Posts
- Events

Search ranking combines:

- Relevance
- Popularity
- Freshness

---

# 21. Recommendation Rules

Feed ranking considers:

- Following
- Engagement
- Trending content
- Recommendations

Shop recommendations affect only shop content.

Event visibility depends on normal feed ranking.

---

# 22. Notification Rules

Users receive notifications for:

- Followers
- Likes
- Comments
- Replies
- Mentions
- Orders
- Payments
- Escrow
- Event tickets

Businesses receive:

- New orders
- Payments received into escrow
- Delivery confirmations
- Escrow releases

---

# 23. Sharing Rules

Permanent URLs exist for:

- Profiles
- Products
- Businesses
- Events
- Posts

Private conversations are never shareable.

Stories are never permanently shareable.

---

# 24. Moderation Rules

Administrators may:

- Remove content
- Suspend accounts
- Restore accounts
- Moderate reports

All actions generate audit logs.

---

# 25. Financial Rules

Platform commission:

**3.5%**

Applied to:

- Product sales
- Event ticket sales

Commission is deducted before business payout.

---

# 26. Recommendation

Every business rule should exist in **one place only**.

Avoid duplicating business rules across API endpoints, services, frontend code, scheduled jobs, or administrative tools.

Instead, centralize rule enforcement within the service layer and reference this document whenever implementing new functionality. If a rule changes—for example, changing the escrow auto-release period from 72 hours to 48 hours—update this document first, then update the implementation accordingly.

This approach keeps engineering, documentation, testing, and product behavior synchronized.

---

# 27. Summary

The Business Rules document defines the operational behavior of CartFlow independent of implementation details.

By documenting platform rules in a centralized location, developers can build consistent features, testers can validate expected behavior, and future changes can be introduced with minimal ambiguity while preserving the integrity of the platform.

---

# End of Document