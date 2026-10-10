# Appendix A. User Flows

> Version: V1.0
>
> Status: Appendix
>
> Last Updated: August 2026

---

# 1. Purpose

This document describes the end-to-end user journeys supported by CartFlow Version 1.

Each flow outlines how users interact with the platform, the decisions made at each step, and the expected outcomes. These flows serve as references for product design, engineering, testing, and user experience validation.

---

# 2. User Types

Document the primary actors:

- Student
- Business
- Administrator
- Guest (Unauthenticated)

---

# 3. Flow Conventions

Explain:

- Start point
- Decision nodes
- Success paths
- Failure paths
- Alternate flows

---

# 4. Student Registration Flow

### Primary Flow

Landing Page

↓

Sign Up

↓

Enter Personal Information

↓

Choose Username

↓

Set Password

↓

Verify Email

↓

Account Created

↓

Complete Profile

↓

Home Feed

### Alternate Flows

- Username already exists
- Email already exists
- Verification expired
- Weak password

---

# 5. Student Login Flow

Landing Page

↓

Login

↓

Enter Credentials

↓

Authentication

↓

Session Created

↓

Redirect to Home Feed

Alternate:

- Invalid credentials
- Locked account
- Unverified account

---

# 6. Business Registration Flow

Student Account

↓

Business Hub

↓

Create Business

↓

Business Information

↓

Business Logo

↓

Delivery Configuration

↓

Business Created

↓

Business Dashboard

---

# 7. Profile Editing Flow

Profile

↓

Edit

↓

Update Information

↓

Validation

↓

Save

↓

Profile Updated

---

# 8. Follow User Flow

Visit Profile

↓

Follow

↓

Relationship Created

↓

Notification Sent

↓

Follower Count Updated

---

# 9. Messaging Flow

Visit Profile

↓

Send Message

↓

Message Request Created

↓

Recipient Receives Request

↓

Recipient Accepts / Replies

↓

Conversation Open

↓

Unlimited Messaging

Failure:

- Blocked
- Suspended account

---

# 10. Activity Inbox Flow

Platform Event

↓

Notification Generated

↓

Activity Inbox

↓

User Opens Notification

↓

Marked as Read

↓

Navigate to Related Content

---

# 11. Create Feed Post Flow

Home Feed

↓

Create Post

↓

Write Caption

↓

Attach Images

↓

Tag Products (Optional)

↓

Publish

↓

Followers Receive Post

---

# 12. Comment Flow

Open Post

↓

Write Comment

↓

Submit

↓

Comment Published

↓

Post Owner Notified

---

# 13. Save Post Flow

Open Post

↓

Save

↓

Saved Collection

↓

Accessible from Profile

---

# 14. Repost Flow

Open Post

↓

Repost

↓

Published to Feed

↓

Original Creator Credited

---

# 15. Share Flow

Select Share

↓

Choose:

- Internal Share
- External Share
- Copy Link

↓

Complete Share

---

# 16. Product Discovery Flow

Home

↓

Shop

↓

Browse Categories

↓

Search

↓

Filter

↓

Open Product

---

# 17. Add to Cart Flow

Product Page

↓

Choose Quantity

↓

Add to Cart

↓

Cart Updated

---

# 18. Cart Delivery Selection Flow

Cart

↓

Choose Delivery Method

↓

Pickup

OR

Seller Delivery

↓

Cart Updated

---

# 19. Checkout Flow

Cart

↓

Review Items

↓

Enter Delivery Address

↓

Select Payment Method

↓

Payment

↓

Verification

↓

Order Created

↓

Receipt Generated

---

# 20. Order Fulfilment Flow

Order Created

↓

Business Accepts

↓

Prepare Order

↓

Ready

↓

Delivered

↓

Customer Confirms

↓

Escrow Released

Alternate:

No Confirmation

↓

72 Hours

↓

Automatic Release

---

# 21. Refund Flow

Customer Requests Refund

↓

Administrator Review

↓

Approve / Reject

↓

Escrow Updated

↓

Customer Notified

---

# 22. Event Purchase Flow

Browse Event

↓

Open Event

↓

Purchase Ticket

↓

Payment

↓

QR Generated

↓

Email Confirmation

---

# 23. Event Check-in Flow

Customer Arrives

↓

QR Scanned

↓

Ticket Validated

↓

Attendance Recorded

---

# 24. Business Product Creation Flow

Business Hub

↓

Products

↓

New Product

↓

Upload Images

↓

Inventory

↓

Pricing

↓

Publish

---

# 25. Discount Creation Flow

Business Dashboard

↓

Products

↓

Select Product

↓

Add Discount

↓

Save

↓

Discount Visible

---

# 26. Business Order Processing Flow

Order Notification

↓

Review Order

↓

Accept

↓

Prepare

↓

Complete

↓

Mark Delivered

↓

Await Escrow Release

---

# 27. Event Creation Flow

Business Hub

↓

Events

↓

Create Event

↓

Configure Details

↓

Publish

↓

Event Live

---

# 28. Search Flow

Open Search

↓

Type Query

↓

Autocomplete

↓

Results

↓

Open Resource

---

# 29. Administration Login Flow

Login

↓

Administrator Authentication

↓

Admin Dashboard

↓

Role Validation

---

# 30. Moderation Flow

Report Submitted

↓

Admin Review

↓

Decision

↓

Action Taken

↓

Audit Log Created

---

# 31. Error Recovery Flows

Document common recovery scenarios:

- Payment failure
- Network interruption
- Session expiration
- Upload failure
- Duplicate submission

---

# 32. Recommendation

Each user flow should remain synchronized with the PRD, business rules, API documentation, and implementation.

Whenever a feature changes, its corresponding flow should be reviewed and updated to ensure that product documentation, engineering documentation, and user experience remain aligned.

Flow diagrams should prioritize clarity over implementation detail so they can be understood by developers, designers, testers, and stakeholders alike.

---

# 33. Summary

The User Flows appendix documents the primary journeys users follow throughout CartFlow, from registration and social interactions to commerce, payments, events, and administration.

These flows provide a shared understanding of platform behavior and serve as the foundation for implementation, testing, and future feature enhancements.

---

# End of Document