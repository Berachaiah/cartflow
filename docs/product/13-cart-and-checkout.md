# 13. Cart and Checkout

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Cart allows users to collect products from one or more businesses before purchasing.

The Checkout process confirms delivery details, payment, and order information before securely processing payment.

The checkout experience should be simple, transparent, and trustworthy.

---

# 2. Objectives

The Cart and Checkout system should:

- Support purchases from multiple businesses.
- Clearly display delivery information.
- Minimize checkout friction.
- Prevent accidental purchases.
- Prepare orders for escrow payment processing.
- Synchronize inventory immediately after payment.

---

# 3. Cart Overview

The Cart contains:

- Products
- Business information
- Quantity
- Delivery option
- Price summary

Products remain in the cart until:

- Purchased
- Removed
- Product becomes unavailable

---

# 4. Cart Layout

```
Shopping Cart

────────────────────────

Business A

Product

Price

Quantity

Subtotal

────────────────────────

Business B

Product

Price

Quantity

Subtotal

────────────────────────

Order Summary

Checkout

```

Products are grouped by business.

---

# 5. Cart Item

Every cart item displays:

- Product Image
- Product Name
- Business Name
- Unit Price
- Quantity
- Total Price

Actions:

- Increase Quantity
- Decrease Quantity
- Remove Item
- Save for Later (Future)

---

# 6. Quantity

Users may:

- Increase quantity
- Reduce quantity

The maximum quantity cannot exceed available inventory.

---

# 7. Delivery Selection

Each business configures available delivery options.

Businesses may enable:

☑ Pickup

☑ Seller Delivery

Customers choose one option during Checkout.

The selected option is stored with the order.

---

# 8. Delivery Coverage

Before Checkout, customers can see:

```
Delivery Coverage

Bells University

Ota

Lagos

Nationwide
```

This helps customers know whether delivery is available to their location.

---

# 9. Pickup Location

If Pickup is available:

Customers can view the pickup location before confirming the order.

Example:

```
Pickup Location

Main Gate

Bells University

Ota
```

Businesses may update pickup locations at any time through Business Hub.

---

# 10. Delivery Address

When Seller Delivery is selected:

Customers provide:

- Full Address
- State
- City
- Phone Number

Addresses are saved for future purchases.

---

# 11. Multiple Businesses

The Cart supports products from multiple businesses.

Each business generates its own order after payment.

Customers complete one checkout process.

---

# 12. Order Summary

Displays:

Products Total

Discount

Platform Fees (if applicable)

Delivery Cost

Grand Total

---

# 13. Coupons

Version 1 does not support coupons.

Businesses instead use product discounts.

Coupons may be introduced in future versions.

---

# 14. Stock Validation

Before payment:

The system verifies:

- Product availability
- Quantity
- Active discounts

If inventory changes during checkout:

Users are informed before payment.

---

# 15. Checkout Flow

```
Cart

↓

Delivery Details

↓

Order Summary

↓

Payment

↓

Payment Successful

↓

Order Created

↓

Receipt

```

---

# 16. Payment

Customers pay once.

Payment enters escrow.

Businesses are immediately notified that payment has been received.

Funds are **not** released immediately.

---

# 17. Escrow Notice

During Checkout, users see:

```
Your payment will be securely held by CartFlow.

The seller will receive payment only after your order is completed.

```

This builds trust for both buyers and businesses.

---

# 18. Inventory Update

Immediately after successful payment:

Inventory decreases automatically.

Out-of-stock products become unavailable.

---

# 19. Checkout Validation

The Checkout page validates:

- Required address
- Delivery option
- Product availability
- Payment success

Validation occurs before order creation.

---

# 20. Order Creation

After successful payment:

The system creates:

- Order
- Order Items
- Escrow Record
- Receipt
- Business Notification

---

# 21. Receipt

Receipts are sent by email.

Receipts include:

- Order Number
- Products
- Prices
- Payment Reference
- Delivery Method
- Business Information

Users may also download receipts from their Order Details page.

---

# 22. Error Handling

Possible errors:

- Product unavailable
- Payment failed
- Inventory changed
- Invalid delivery address

Users receive clear error messages.

---

# 23. Performance

Cart updates should occur instantly.

Totals should update dynamically.

Checkout should complete within a few seconds under normal conditions.

---

# 24. Database Entities

Primary tables:

- carts
- cart_items
- checkout_sessions
- delivery_addresses

---

# 25. API Endpoints

GET /api/cart

POST /api/cart/items

PUT /api/cart/items/{id}

DELETE /api/cart/items/{id}

POST /api/checkout

GET /api/checkout/{id}

---

# 26. Future Enhancements

Potential future additions:

- Save for Later
- Coupon Codes
- Gift Cards
- Buy Now
- Split Payments
- Scheduled Delivery
- One-Click Checkout

---

# 27. Summary

The Cart and Checkout system is designed to provide a seamless and secure purchasing experience.

By grouping products by business, validating inventory before payment, supporting flexible delivery methods, and integrating directly with the escrow payment system, CartFlow ensures a reliable and trustworthy checkout process for both buyers and sellers.

---

# Implementation Status — as built (August 16, 2026)

**Cart: built client-side. Checkout: not built.**

The cart lives as a sheet on the Shop page (`app/templates/shop.html`,
`#cartSheet`), holding line items with quantities and a total, persisted in
`localStorage` under `cartflow-cart`. It is grouped and totalled in the browser
because there is no `carts` or `cart_items` table to write to — nothing about it
survives a different device or a cleared browser.

**Checkout stops there deliberately.** §6-§14 need, in order: a `products` table to
validate against, an `orders` table to write, a payment intent, and the escrow
ledger (doc 15). None of them exists. A checkout button that took a delivery
address and a card would be collecting payment details for an order that cannot be
recorded — the one class of dishonesty this codebase refuses, which is the same rule
that keeps a specimen order off `/orders` (doc 14) and the example revenue figure
off the Business Hub (doc 16).

So the cart sheet's action is an honest one: it explains that checkout arrives with
payments, rather than opening a form.

**What must land first:** `products`, `orders` + `order_items`, the payment
provider integration (`PAYMENT_PROVIDER` in `app/core/config.py`), then escrow.
Inventory validation (§8) and delivery-method selection (§10) are part of the same
slice.

---

# End of Document