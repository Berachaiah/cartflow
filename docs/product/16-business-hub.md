# 16. Business Hub

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 15, 2026

---

# 1. Purpose

The Business Hub is the central management area for all Business Accounts on CartFlow.

It allows businesses to:

- Manage products
- Manage inventory
- Manage events
- Manage orders
- Manage payouts
- Configure delivery settings
- Update pickup locations
- View analytics
- Manage business profile information
- Monitor customer interactions

The Business Hub acts as the operational dashboard of the platform.

---

# 2. Objectives

The Business Hub should:

- Be simple enough for student businesses.
- Scale to larger businesses.
- Provide all essential operations in one place.
- Offer analytics without overwhelming users.
- Make inventory management easy.
- Give businesses visibility into orders and revenue.

---

# 3. Access

The Business Hub is available to any account with the **seller capability**
(`is_seller`) — that is, any account that owns a business, regardless of its
identity type.

A student, an individual, or a standalone business can all reach the Hub. A
non-selling account (a student or individual who hasn't started a business yet)
does not see the Hub until they tap **"Start selling"**, which creates the
business they own and enables the capability. Their underlying account type does
not change — a student who starts selling is still a student who now also sells.

---

# 4. Business Hub Navigation

Mobile:

```
Business Hub

Dashboard
Products
Orders
Events
Analytics
Operations
Finance
Settings
```

Desktop:

Sidebar:

```
Dashboard
Products
Orders
Events
Analytics
Operations
Finance
Settings
```

Sub-navigation may appear inside each section.

---

# 5. Dashboard

The Dashboard provides an overview.

Displayed metrics:

Today's Revenue

Pending Orders

Pending Escrow

Products Sold

Active Products

Active Events

New Followers

Unread Messages

Low Stock Alerts

Recent Reviews

---

# 6. Dashboard Cards

Example:

```
Revenue

₦48,200
+18%

Pending Escrow

₦13,000

Orders

12

Low Stock

3
```

---

# 7. Products

Businesses can:

- Create products
- Edit products
- Delete products
- Archive products
- Restock inventory
- Add discounts
- Upload images
- Update prices

---

# 8. Inventory

Inventory displays:

- Product
- Quantity
- Reserved Quantity
- Available Quantity
- Low Stock Indicator

Inventory updates automatically after successful payment.

---

# 9. Low Stock Alerts

Businesses receive notifications when inventory falls below a configurable threshold.

Example:

```
Luxury Oud Perfume

Only 3 left.
```

---

# 10. Orders

Businesses can:

- View orders
- Confirm orders
- Mark Preparing
- Mark Ready for Pickup
- Mark Delivered
- Contact customers
- View receipts
- View escrow status

---

# 11. Events

Businesses can:

- Create events
- Edit events
- Publish events
- Cancel events
- View ticket sales
- View attendance
- View event analytics

One business may own multiple events.

---

# 12. Event Check-In

Businesses can access:

Event Check-In

Features:

- QR scanning
- Search attendee
- Search ticket
- Manual validation
- Attendance tracking

---

# 13. Analytics

Businesses can view:

Revenue

Orders

Conversion Rate

Views

Product Performance

Event Performance

Follower Growth

Message Response Time

Top Products

Top Posts

Top Events

---

# 14. Operations

Operations contains:

Delivery Settings

Pickup Locations

Business Status

Current Location

Operating Hours

---

# 15. Delivery Settings

Businesses choose:

☑ Pickup

☑ Seller Delivery

Businesses may enable either or both.

---

# 16. Delivery Coverage

Businesses specify:

- Bells University
- Ota
- Ogun State
- Lagos
- Nationwide

Customers can see delivery coverage before purchasing.

---

# 17. Pickup Locations

Businesses may create multiple pickup locations.

Example:

```
Main Gate

Bells University

Ota
```

Pickup locations can be updated anytime.

---

# 18. Update Current Location

Businesses can quickly update where they are.

Example:

```
📍 Update Current Location
```

Useful during holidays or temporary relocation.

---

# 19. Business Status

Businesses may choose:

🟢 Open

🟡 Busy

🔴 Closed

🌴 Holiday Mode

Customers can see the status.

---

# 20. Operating Hours

Businesses may optionally configure:

Monday:

9 AM - 6 PM

Tuesday:

9 AM - 6 PM

and so on.

---

# 21. Finance

Finance displays:

Revenue

Pending Escrow

Released Escrow

Refunds

Payouts

Commissions

Net Earnings

---

# 22. Payout History

Businesses can view:

- Amount
- Order
- Date
- Escrow Release Date
- Status

---

# 23. Business Bank Accounts

Businesses configure:

- Bank
- Account Number
- Account Name

Supported banks come directly from the payment provider.

---

# 24. Customers

Businesses can view:

- Followers
- Reviews
- Customer Count
- Repeat Customers

Businesses cannot see who added products to cart.

---

# 25. Reviews

Businesses can:

- View reviews
- Reply to reviews

Businesses cannot delete reviews.

---

# 26. Business Profile Management

Businesses can edit:

- Logo
- Name
- Username
- Bio
- Website
- Delivery Coverage
- Pickup Locations
- Contact Information

---

# 27. Business Profile Tabs

Public Business Profiles contain:

Products

Posts

Events

Reviews

Businesses also retain normal social functionality:

- Likes
- Saves
- Reposts
- Comments
- Shares
- Following
- Messaging

---

# 28. Notifications

Businesses receive notifications for:

- New Orders
- Low Inventory
- Reviews
- New Followers
- Escrow Released
- Ticket Sales
- Payouts

---

# 29. Error Handling

Businesses receive clear errors for:

- Failed uploads
- Failed payouts
- Payment failures
- Inventory conflicts
- Validation errors

Technical errors are logged internally.

---

# 30. Database Entities

Primary tables:

- businesses
- business_locations
- business_delivery_areas
- business_status
- business_analytics
- inventory
- inventory_logs

---

# 31. API Endpoints

GET /api/business/dashboard

GET /api/business/analytics

GET /api/business/orders

GET /api/business/products

GET /api/business/events

POST /api/business/location

POST /api/business/status

POST /api/business/pickups

GET /api/business/finance

---

# 32. Performance

The Business Hub should:

- Load quickly.
- Cache analytics.
- Paginate large datasets.
- Support real-time order updates.
- Support real-time inventory updates.

---

# 33. Future Enhancements

Potential future additions:

- Business Teams
- Employee Permissions
- Multiple Store Locations
- Advanced Analytics
- Scheduled Posts
- Bulk Inventory Import
- CRM Features
- Customer Segmentation

---

# 34. Summary

The Business Hub serves as the operational backbone of CartFlow.

It allows businesses to manage products, events, orders, inventory, finances, analytics, and customer interactions from one centralized interface while remaining simple enough for student entrepreneurs and scalable enough for future growth.

---

# Implementation Status — as built (August 16, 2026)

**Route:** `GET /dashboard` — `app/routers/pages.py:dashboard` →
`app/templates/dashboard.html`.
**API:** `app/routers/business.py` — `GET /api/business/profile`,
`PATCH /api/business/profile`.
**Tests:** `tests/test_business_hub.py`.

**Three server-rendered states**, decided in the route rather than hidden with CSS,
so a visitor's HTML never contains a hub they can't use:

| State | What renders |
|---|---|
| signed out | a log-in prompt, and none of the hub markup |
| signed in, no shop | §3's **Start selling** form (`POST /api/auth/business/upgrade`) |
| owns a business | the hub — §4's eight panels |

**The gate is the `organizations` row (`owner_user_id`), never `users.is_seller`.**
The flag is a denormalized mirror; if the two ever drift, a hub rendered off the flag
would have no business behind it. `PATCH /api/business/profile` follows the same rule,
which is why "no business" is a **404 there rather than a 403** — the row is looked up
*from* the caller, so "not yours" and "doesn't exist" are the same condition.

**Real today:**

- The business identity — name, state, pickup address, verification status — from the
  owned row.
- **Follower counts**, from `user_follows`. This is the hub's only live number, and
  `test_hub_follower_count_is_real` asserts it against an actual follow.
- **Editing** name, state and pickup address via `PATCH /api/business/profile`.
  Partial by design (`exclude_unset`), so the pickup sheet can submit one field; an
  emptied textarea clears the column rather than storing `""`. `status`, `slug` and
  `owner_user_id` are ignored if sent — **a seller cannot verify their own shop.**

**Honest zeros everywhere else.** §30 lists seven tables that don't exist, so
Products, Orders, Events, Analytics, Operations and Finance render empty states that
each name what they are waiting on. **§6's ₦48,200 example revenue must never
render** — a seller reading their own hub has no way to tell an illustration from
their real takings, and `test_hub_never_renders_the_example_revenue` pins it.

**Terminology:** "Business Hub" throughout — never "Merchant Hub".

---

# End of Document