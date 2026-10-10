# 15. Payments, Escrow and Payouts

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Payments system handles all financial transactions within CartFlow.

It ensures customers can purchase confidently while protecting businesses through a transparent escrow workflow.

Funds remain securely held until delivery has been confirmed or automatically released according to platform rules.

---

# 2. Objectives

The payment system should:

- Process secure payments
- Protect buyers
- Protect businesses
- Prevent fraud
- Support escrow
- Support manual intervention
- Provide complete financial records

---

# 3. Payment Providers

Version 1 supports:

- Anchor (Preferred)
- Paystack (Fallback)

Future providers may include:

- Flutterwave
- Stripe

Only one payment gateway is active at a time.

---

# 4. Supported Payment Methods

Customers may pay using:

- Debit Cards
- Bank Transfer
- USSD (provider dependent)
- Mobile Wallets (provider dependent)

Supported methods depend on the payment gateway.

---

# 5. Payment Flow

```
Checkout

↓

Payment Gateway

↓

Payment Successful

↓

Escrow Account

↓

Seller Confirms Order

↓

Delivered

↓

Customer Confirms

↓

Funds Released

↓

Business Paid
```

---

# 6. Escrow

Escrow protects both parties.

After payment:

Funds belong to neither customer nor business.

Funds remain securely held until the order is completed.

---

# 7. Escrow Status

Every order displays:

Pending

Held

Released

Refunded

Disputed

Both customer and business can view the escrow status.

---

# 8. Customer Experience

After payment:

Customers immediately see:

```
Payment Successful

Your payment is being securely held by CartFlow.

The seller will receive payment after your order is completed.
```

This increases trust.

---

# 9. Business Experience

Businesses immediately receive:

```
New Order Received

Payment has been secured.

Prepare the customer's order.
```

Businesses know payment exists but cannot withdraw it yet.

---

# 10. Seller Confirmation

Businesses confirm:

Order Accepted

↓

Preparing

↓

Ready

↓

Delivered

These updates notify the customer.

---

# 11. Customer Confirmation

Once the customer receives the order:

```
Confirm Delivery
```

Immediately releases escrow.

---

# 12. Automatic Release

If:

Business marks:

Delivered

AND

Customer does not respond

Escrow automatically releases after:

```
72 Hours
```

Customers receive reminder notifications before release.

---

# 13. Disputes

If the customer opens a dispute before auto-release:

Escrow remains locked.

No payout occurs until the dispute is resolved.

---

# 14. Refunds

Refunds may occur if:

- Seller cancels
- Customer receives the wrong item
- Fraud
- Order cannot be fulfilled

Refunds are processed through the payment provider.

---

# 15. Manual Escrow Release

Administrators can manually:

Release funds

Hold funds

Refund payment

Adjust payment status

Every action is fully audited.

---

# 16. Manual Intervention

Examples:

Payment gateway failure

Escrow release failure

Duplicate payment

Incorrect payout

Administrator intervention is recorded permanently.

---

# 17. Business Bank Accounts

Businesses configure:

- Bank
- Account Number
- Account Name

The platform verifies supported banks through the payment provider.

If a bank is unsupported, users receive a clear warning.

---

# 18. Supported Banks

Businesses select their bank from a predefined list.

Manual typing is not permitted.

This avoids spelling inconsistencies.

The list updates automatically when supported by the payment provider.

---

# 19. Payouts

When escrow releases:

Funds are transferred to the business.

Businesses receive:

```
Payment Released

₦8,000

Royal Fragrance
```

---

# 20. Transaction Fees

CartFlow deducts:

Platform Commission

before the final payout.

Businesses can always view:

Gross Amount

Commission

Net Amount

---

# 21. Receipts

Customers receive:

- Email Receipt
- Downloadable Receipt

Businesses receive:

- Payout Receipt

Receipts contain:

Order Number

Payment Reference

Amount

Business

Customer

Date

---

# 22. Transaction History

Customers see:

Payments

Refunds

Receipts

Businesses additionally see:

Payouts

Commission

Revenue

---

# 23. Failed Payments

Examples:

Card declined

Bank unavailable

Timeout

Cancelled

Users receive:

Retry Payment

without creating duplicate orders.

---

# 24. Payment Security

Payment details never touch CartFlow servers.

Sensitive card data remains with the payment gateway.

All communication uses HTTPS.

---

# 25. Financial Reports

Businesses can view:

Revenue

Pending Escrow

Released Escrow

Refunds

Platform Fees

Net Earnings

Administrators have platform-wide visibility.

---

# 26. Database Entities

Primary tables:

payments

escrow_transactions

payouts

refunds

business_bank_accounts

payment_provider_logs

---

# 27. API Endpoints

POST /api/payments/initialize

POST /api/payments/webhook

GET /api/payments/{id}

POST /api/payments/verify

POST /api/escrow/release

POST /api/escrow/refund

GET /api/payouts

---

# 28. Future Enhancements

Potential future additions:

Split Payments

Installments

Wallet System

Subscription Billing

International Payments

Automatic Tax Reports

Multi-currency Support

---

# 29. Summary

The CartFlow payment system combines secure payment processing with escrow protection to create trust between customers and businesses.

By delaying payouts until orders are completed, providing transparent payment statuses, supporting disputes, and maintaining detailed financial records, the platform establishes a reliable foundation for social commerce.

---

# Implementation Status — as built (August 16, 2026)

**Not built.** No payment integration, no escrow ledger, no payouts. There are no
`payments`, `escrow_transactions`, `payouts` or `wallets` tables, and no provider
client — `PAYMENT_PROVIDER` in `app/core/config.py` (`paystack` | `anchor`) is a
setting with nothing reading it yet.

**What IS live is the explanation**, and only because it costs nothing to be honest
about a rule that hasn't shipped:

- `app/templates/orders.html` renders the four escrow states and the **72-hour
  auto-release** as a reference sheet, reachable from the page head on mobile and the
  desktop aside. Written for someone deciding whether to trust the app, not for
  someone who has already paid.
- `app/templates/shop.html`'s checkout button says outright that checkout arrives
  with payments and escrow, and that the cart is saved in the meantime.
- `app/templates/dashboard.html`'s Finance panel renders honest zeros and an empty
  payout history. It must never render doc 16 §6's ₦48,200 example figure — a seller
  reading their own hub cannot tell an illustration from their real takings, and
  `tests/test_business_hub.py::test_hub_never_renders_the_example_revenue` pins that.

**Order of work when this starts:** provider client → `payments` → `orders`
(doc 14) → escrow ledger → dispute resolution → payouts. Escrow release is what
makes the order lifecycle meaningful, so it cannot lag the orders table by much.

---

# End of Document