# 11. Activity and Notifications

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Activity system keeps users informed about everything happening on their account.

It combines social interactions, commerce updates, order progress, event notifications, and system announcements into one centralized inbox.

Unlike Messages, the Activity Inbox is notification-driven rather than conversation-driven.

---

# 2. Objectives

The Activity Inbox should:

- Encourage users to return to the app.
- Notify users about important actions.
- Reduce uncertainty during purchases.
- Improve engagement.
- Keep businesses informed.
- Keep customers informed.

---

# 3. Access

Users access Activity by tapping the notification icon.

Mobile:

Top-right corner of the Home Feed.

Desktop:

Top-right navigation bar.

---

# 4. Notification Categories

Notifications are grouped into categories.

- Social
- Shop
- Orders
- Events
- Business
- System

---

# 5. Social Notifications

Examples:

- Someone followed you.
- Someone liked your post.
- Someone commented on your post.
- Someone replied to your comment.
- Someone mentioned you.
- Someone reposted your post.
- Someone shared your profile.
- Someone liked your comment.

Selecting a notification opens the relevant content.

---

# 6. Shop Notifications

Examples:

- Product back in stock.
- Product price changed.
- Discount started.
- Discount ending soon.
- Wishlist item available (future).

Selecting the notification opens the Product page.

---

# 7. Order Notifications

Customers receive:

- Payment successful
- Payment pending
- Seller confirmed order
- Seller preparing order
- Order ready for pickup
- Seller marked as delivered
- Confirm delivery reminder
- Escrow released
- Refund initiated
- Refund completed

Businesses receive:

- New order
- Customer paid
- Customer confirmed delivery
- Escrow released
- New review

---

# 8. Event Notifications

Examples:

- Ticket purchased
- Ticket emailed
- Event reminder
- Event tomorrow
- Event today
- Event cancelled
- Event updated
- Ticket scanned

---

# 9. Business Notifications

Businesses receive notifications for:

- Low inventory
- Out of stock
- New follower
- Product review
- Business mentioned
- Product tagged
- Analytics milestone
- Payout completed

---

# 10. System Notifications

Examples:

- Password changed
- Login detected
- Maintenance announcement
- New feature available
- Policy updates
- Security alerts

---

# 11. Notification Card

Each notification contains:

- Icon
- Sender (if applicable)
- Description
- Timestamp
- Read status

Example:

❤️

Royal Fragrance liked your post.

2 hours ago

---

# 12. Read Status

Notifications may be:

Unread

Read

Unread notifications display a colored indicator.

---

# 13. Bulk Actions

Users can:

- Mark all as read
- Delete selected notifications
- Clear all read notifications

---

# 14. Notification Retention

Notifications remain available for a configurable period.

Older notifications may be archived automatically.

Critical notifications (payments, receipts, disputes) remain accessible for longer.

---

# 15. Push Notifications

Supported devices receive push notifications for:

- Messages
- Orders
- Event reminders
- Mentions
- New followers
- Payment updates

Users may disable push notifications.

---

# 16. Email Notifications

Certain actions additionally generate emails.

Examples:

- Order receipt
- Ticket purchase
- Password reset
- Escrow release
- Refund
- Business payout

---

# 17. Notification Preferences

Users can configure:

Social

☑ Likes

☑ Comments

☑ Followers

☑ Mentions

Shop

☑ Discounts

☑ Product updates

Orders

☑ Order updates

☑ Delivery updates

Events

☑ Reminders

☑ Ticket updates

System

☑ Security

☑ Maintenance

---

# 18. Deep Linking

Every notification opens directly to its related resource.

Examples:

Like → Post

Order → Order Details

Ticket → Ticket Details

Product → Product Page

Business → Business Profile

---

# 19. Notification Priority

Highest Priority

- Payment failures
- Security alerts
- Disputes
- Refunds

Medium Priority

- Orders
- Events
- Messages

Low Priority

- Likes
- Followers
- Saves

---

# 20. Notification Grouping

Similar notifications may be grouped.

Example:

```
Royal Fragrance and 14 others liked your post.
```

Instead of 15 separate notifications.

---

# 21. Search

Users can search notifications.

Search by:

- Username
- Business
- Product
- Event

---

# 22. Performance

Notifications should:

- Load incrementally.
- Sync in real time.
- Cache recent items.
- Update badge counts instantly.

---

# 23. Security

Notifications must never expose:

- Sensitive payment details
- Passwords
- Personal banking information

Only authorized users may access their notifications.

---

# 24. Database Entities

Primary tables:

- notifications
- notification_preferences
- notification_reads
- push_tokens

---

# 25. API Endpoints

GET /api/notifications

POST /api/notifications/read

POST /api/notifications/read-all

DELETE /api/notifications/{id}

GET /api/notifications/preferences

PUT /api/notifications/preferences

---

# 26. Future Enhancements

Potential future additions:

- Rich push notifications
- Notification reactions
- AI notification summaries
- Scheduled digests
- Smart notification prioritization

---

# 27. Summary

The Activity and Notification system serves as the central communication hub for all platform events.

By combining social engagement, commerce updates, order tracking, event reminders, and system alerts into a unified inbox, CartFlow keeps users informed while encouraging frequent interaction with the platform.

---

# Implementation Status — as built (August 18, 2026)

**One category is real, and exactly one.** There is still no `notifications`
table, no push/email fan-out and no unread badge. What exists as of August 17-18
is the page: `GET /notifications` (`app/routers/pages.py`) renders
`app/templates/notifications.html` instead of the Home bell toasting "Activity
inbox — coming soon".

It queries the **follow graph**, not a notifications store. Of the six categories
in §4 (Social, Shop, Orders, Events, Business, System), follows are the only
events that exist: `user_follows` is a real table, so "X started following you"
is a genuine notification rendered from the edge itself.
`follow_service.list_followers` already returns the edge's `created_at` as
`followed_at` — its docstring anticipated this caller — so a row costs no extra
query, and the `is_following` flag on the same row is what lets the Follow-back
button render in the correct state without one request per row.

Signed out redirects to `/login?next=/notifications`: "your activity" has no
useful public rendering.

Still missing, and named in the page's own pending list rather than faked:

- **No read state and no unread badge** (§12-13). Both are server state with
  nowhere to live. A localStorage flag would mark an event read on one device and
  unread on another; a badge counting total followers would re-alarm every time
  you cleared it.
- **`show` grows the window, it does not page it.** An activity list is read
  top-down, so the second screenful must not replace the first — `?show=40`
  re-renders rows 1-40 and the anchor returns you to your place. FastAPI clamps
  it to 1-200, so a hand-typed `?show=99999` is a 422, not a full-table render.

Two things still worth noting because they change what the rest costs:

- **Transactional email already works.** `app/integrations/smtp_client.py` sends
  verification and password-reset mail through the templates in
  `app/templates/emails/`, so the notification system needs a table and a
  dispatcher, not a mail layer.
- **Most of the events this inbox would carry don't exist yet.** Likes, comments,
  order status changes, escrow releases, ticket purchases — every one needs its
  own table first (docs 06, 14, 15, 17).

**Tests:** `tests/test_inboxes.py` creates a real follow edge and asserts the row
renders with its handle, the verb phrase, the display name and a Follow-back
button carrying the right label — the mutual case must say "Following", since
"Follow back" on someone you already follow is an unfollow nobody asked for. The
window is pinned at both ends: 21 followers render 20 rows plus
`?show=40#activity` labelled "(20 of 21)", and `?show=0` / `?show=201` /
`?show=99999` are each a 422. `time_ago`'s boundaries are checked either side of
every threshold with an injected `now` rather than by sleeping, including the
future-timestamp case (clock skew reads as "now", not "in -3m").

---

# End of Document