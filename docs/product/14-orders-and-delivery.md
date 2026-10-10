# 14. Orders and Delivery

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Orders system manages every purchase after checkout.

It provides customers and businesses with complete visibility into the progress of an order, from payment until completion.

The system also integrates with CartFlow's escrow payment workflow to ensure fairness for both buyers and sellers.

---

# 2. Objectives

The Orders module should:

- Track every purchase.
- Increase customer trust.
- Keep businesses informed.
- Integrate with escrow.
- Support pickups.
- Support seller delivery.
- Handle disputes fairly.
- Provide complete order history.

---

# 3. Order Lifecycle

```
Cart

↓

Checkout

↓

Payment Successful

↓

Order Created

↓

Seller Notified

↓

Seller Confirms Order

↓

Preparing Order

↓

Ready for Pickup
or
Delivered

↓

Customer Confirms Delivery

↓

Escrow Released

↓

Order Completed
```

---

# 4. Order Statuses

Orders move through predefined statuses.

Pending Payment

↓

Paid

↓

Seller Confirmed

↓

Preparing

↓

Ready for Pickup

or

Delivered

↓

Completed

Possible alternative states:

Cancelled

Refunded

Disputed

---

# 5. Customer Order Page

Each order displays:

- Order Number
- Business
- Products
- Quantity
- Payment Status
- Escrow Status
- Delivery Method
- Timeline
- Receipt

Actions:

- View Receipt
- Contact Business
- Confirm Delivery
- Raise Dispute

---

# 6. Business Order Page

Businesses can view:

- Customer
- Products
- Delivery Method
- Delivery Address (if applicable)
- Pickup Details
- Timeline
- Payment Status
- Escrow Status

Actions:

- Confirm Order
- Mark Preparing
- Mark Ready for Pickup
- Mark Delivered
- Contact Customer

---

# 7. Order Timeline

Every order contains a visible timeline.

Example:

```
✔ Payment Successful

✔ Seller Confirmed

✔ Preparing

✔ Ready for Pickup

✔ Completed
```

Customers always know the current stage.

---

# 8. Delivery Methods

Supported methods:

☑ Pickup

☑ Seller Delivery

Businesses choose available options in Business Hub.

Customers choose during Checkout.

---

# 9. Pickup Orders

Businesses specify:

Pickup Location

Customers receive:

Pickup Address

Pickup Instructions (optional)

Customers collect their order.

---

# 10. Seller Delivery

Businesses manually deliver the order.

Customers provide:

- Address
- Phone Number

The platform does not assign couriers.

---

# 11. Business Confirmation

After receiving payment:

Businesses must confirm the order.

Customers receive:

```
Royal Fragrance has confirmed your order.
```

---

# 12. Preparing

Businesses may optionally mark:

Preparing

Customers receive a notification.

---

# 13. Ready for Pickup

For Pickup orders:

Businesses select:

Ready for Pickup

Customers receive:

```
Your order is ready for pickup.
```

---

# 14. Delivered

For Seller Delivery:

Businesses mark:

Delivered

Customers receive:

```
Your order has been marked as delivered.

Please confirm if you have received it.
```

---

# 15. Customer Confirmation

Customers confirm once the order has been received.

Confirmation immediately releases escrow funds.

---

# 16. Auto Release

If:

- Business marks Delivered
- Customer does not respond

Escrow automatically releases funds:

```
72 Hours

after delivery confirmation.
```

Customers receive reminder notifications before auto-release.

---

# 17. Escrow Status

Orders display:

Pending

Held

Released

Refunded

This status remains visible throughout the order lifecycle.

---

# 18. Order History

Customers can view:

Current Orders

Completed Orders

Cancelled Orders

Refunded Orders

Businesses see identical categories.

---

# 19. Receipts

Receipts include:

- Order Number
- Products
- Prices
- Payment Reference
- Delivery Method
- Business
- Date

Receipts are:

- Emailed
- Downloadable

---

# 20. Disputes

Customers may raise disputes.

Examples:

- Wrong item
- Missing item
- Damaged product
- Order never received

Opening a dispute pauses escrow release until resolved.

---

# 21. Refunds

Administrators may initiate refunds after reviewing disputes.

Refund status:

Pending

↓

Approved

↓

Completed

Customers receive notifications at each stage.

---

# 22. Order Cancellation

Customers may cancel only before the business confirms the order.

Businesses may cancel before preparing the order.

Cancelled orders follow the refund workflow where applicable.

---

# 23. Notifications

Customers receive notifications for:

- Payment Successful
- Seller Confirmed
- Preparing
- Ready for Pickup
- Delivered
- Escrow Released
- Refund
- Dispute Updates

Businesses receive:

- New Order
- Customer Paid
- Customer Confirmed Delivery
- Escrow Released
- New Dispute

---

# 24. Performance

Order pages should:

- Load instantly.
- Update in real time.
- Display live status changes.
- Cache completed orders.

---

# 25. Database Entities

Primary tables:

- orders
- order_items
- order_status_history
- deliveries
- disputes
- refunds

---

# 26. API Endpoints

GET /api/orders

GET /api/orders/{id}

POST /api/orders/{id}/confirm

POST /api/orders/{id}/preparing

POST /api/orders/{id}/ready

POST /api/orders/{id}/delivered

POST /api/orders/{id}/confirm-delivery

POST /api/orders/{id}/dispute

---

# 27. Future Enhancements

Potential future additions:

- Courier integration
- Live delivery tracking
- Scheduled delivery
- Pickup QR verification
- Partial refunds
- Order modification
- Gift orders

---

# 28. Summary

The Orders system provides a transparent and trustworthy post-purchase experience.

By combining clear order statuses, real-time notifications, flexible delivery methods, dispute management, and escrow-based payments, CartFlow creates confidence for both customers and businesses while maintaining a simple workflow suitable for campus commerce and future expansion.

---

# Implementation Status — as built (August 16, 2026)

**Route:** `GET /orders` — `app/routers/pages.py:orders` →
`app/templates/orders.html`.
**Tests:** `tests/test_orders_page.py`.

**None of §25's six tables exists** — `orders`, `order_items`,
`order_status_history`, `deliveries`, `disputes`, `refunds` — and neither do
products, a cart row, or a payment record. So the page renders **§18's four history
categories honestly empty** (Current · Completed · Cancelled · Refunded) and never a
specimen order.

That rule is stricter here than anywhere else in the app, and the reason is worth
writing down: a sample order card carries a business name, an amount, a payment
reference and an escrow state, so it reads as *"you bought this and your money is
being held"*. A fabricated order is a lie about the user's own money. The test
`tests/test_orders_page.py::test_orders_never_renders_a_fake_order` asserts that no
`₦` figure appears anywhere on the page.

**What the page does carry, and all of it is real specification rather than
invented data:**

- **§3 lifecycle** — the eight stages, as a numbered rail, with who acts at each.
- **§4/§17 statuses** — all ten in a reference sheet, colour-coded by kind (waiting,
  in progress, done, exception).
- **§8-§10 delivery** — pickup vs seller delivery, including the surprising part
  stated *before* purchase rather than after: **CartFlow does not assign couriers.**
- **§15-§16 escrow** — the four states plus the 72-hour auto-release.
- **§20-§22 problems** — disputes, cancelling, refunds. Receipts are marked as
  waiting on the orders/payments tables.

**One real query.** A seller's *incoming* orders belong to the Business Hub (§6), so
someone who owns a business gets a card pointing at `/dashboard#orders` instead of
being left to wonder where their sales went. The gate is the `organizations` row
(`owner_user_id`), not the denormalized `users.is_seller` flag.

**Signed out is a page, not a redirect** — `/orders` is bookmarkable, and the escrow
and lifecycle explainers are exactly what someone deciding whether to trust the app
wants to read before creating an account.

---

# End of Document