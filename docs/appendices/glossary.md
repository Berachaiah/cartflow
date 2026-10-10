# Appendix A. Glossary

> Version: V1.0
>
> Status: Reference Documentation
>
> Last Updated: August 2026

---

# 1. Purpose

This glossary defines the terminology used throughout the CartFlow documentation.

Its objectives are to:

- Ensure consistent terminology.
- Reduce ambiguity.
- Improve communication between developers, designers, testers, administrators, and stakeholders.
- Provide a quick reference for new contributors.

---

# A

## Activity Inbox

A centralized page where users receive activity-related notifications such as:

- New followers
- Likes
- Comments
- Replies
- Mentions
- Reposts
- Order updates
- Business interactions

Unlike email, the Activity Inbox is part of the CartFlow application.

---

## Admin Panel

The internal management dashboard used by administrators to manage users, businesses, products, events, payments, moderation, analytics, and system configuration.

---

## Analytics

Aggregated platform data used to measure performance, engagement, revenue, growth, and operational health.

---

## API

Application Programming Interface.

A collection of endpoints allowing clients or future third-party applications to communicate with CartFlow.

---

## API Key

A unique credential issued to developers in future versions to authenticate API requests.

---

## Audit Log

An immutable record of important administrative or financial actions performed within the platform.

---

# B

## Background Job

A task executed outside the normal HTTP request lifecycle.

Examples include:

- Sending emails
- Releasing escrow
- Expiring stories
- Generating receipts
- Cleaning media

---

## Business

A seller account representing an individual, organization, or event organizer offering products, services, or events.

---

## Business Hub

The management dashboard where businesses control:

- Products
- Inventory
- Orders
- Events
- Analytics
- Operations
- Pickup Locations
- Delivery Coverage

---

## Business Profile

The public-facing profile representing a business.

It contains:

- Logo
- Bio
- Website
- Products
- Feed Posts
- Events
- Reviews

---

# C

## Cart

A temporary collection of products selected by a customer before checkout.

Each cart item stores its chosen delivery method.

---

## CartFlow

The social commerce platform described throughout this documentation.

---

## Category

A classification assigned to products to improve browsing and search.

---

## Checkout

The process where a customer confirms an order, selects delivery, and completes payment.

---

## Cloudinary

The cloud media platform used for storing, transforming, and delivering images.

---

## Commission

The percentage retained by CartFlow from completed transactions.

Version 1 commission:

3.5%

---

## Customer

Any user purchasing products or event tickets.

Businesses may also act as customers.

---

# D

## Delivery Coverage

The geographical locations where a business is willing to deliver orders.

---

## Delivery Option

The fulfillment method selected for an order.

Version 1 supports:

- Pickup
- Seller Delivery

Businesses may enable either or both.

---

## Discover

The page where users browse recommended businesses, products, and accounts.

---

# E

## Escrow

A payment protection mechanism where customer funds are held until the order has been confirmed as delivered or automatically released according to platform policy.

---

## Event

A scheduled activity created by a business.

Examples:

- Parties
- Dinners
- Conferences
- Workshops
- Concerts

---

## Event Organizer

A business account responsible for creating and managing events.

Event organizers are businesses but are presented as businesses rather than being labeled "Brand Owners."

---

# F

## Feed

The primary content stream where users view posts from followed accounts, recommended businesses, and trending content.

---

## Follow

The relationship created when one account subscribes to another account's public content.

---

# G

## GMV (Gross Merchandise Value)

The total value of all completed transactions before commissions, refunds, or deductions.

---

# H

## Home Feed

The default landing page displaying posts ranked using engagement, relevance, following relationships, and recommendations.

---

# I

## Inventory

The quantity of available stock for a product.

---

# J

## Jinja2

The templating engine used to render HTML pages in the FastAPI application.

---

# L

## Like

A social interaction indicating appreciation of a post.

---

## Location

The current operating location of a business.

Businesses may update this whenever they relocate.

This is different from the Pickup Location.

---

# M

## Mention

A reference to another user or business using the @username syntax.

---

## Message Request

The first message sent to a user who has not yet accepted communication.

After acceptance or a reply, the conversation becomes unrestricted.

---

# N

## Notification

An alert informing users about activity, orders, payments, or system events.

---

# O

## Order

A confirmed purchase consisting of one or more products from a single business.

---

## Order Status

The current lifecycle stage of an order.

Examples:

- Pending
- Paid
- Processing
- Delivered
- Completed
- Refunded

---

# P

## Pickup Location

The location selected by a business where customers collect orders.

Businesses may change this at any time.

---

## Post

A piece of content published to the feed.

Posts may include:

- Text
- Images
- Tagged Products
- Event References

---

## Product

An item listed for sale by a business.

---

## Product Tag

A reference attached to a feed post linking directly to a product.

---

## Profile

The public page representing a student or business account.

---

# Q

## QR Code

A unique machine-readable code generated for each event ticket.

Each QR code becomes invalid immediately after successful scanning.

---

# R

## Recommendation Engine

The system responsible for recommending products, businesses, and content.

Version 1 uses rule-based ranking.

Machine learning may be introduced in future versions.

---

## Redis

An in-memory data store used for caching, background jobs, and rate limiting.

Optional in Version 1.

---

## Repost

A feature allowing users to share another user's post to their own followers while preserving attribution.

---

# S

## Seller Delivery

A delivery method where the business delivers the purchased products directly to the customer.

---

## Shop

The marketplace section containing all products available for purchase.

---

## Story

Temporary content that automatically expires after 24 hours.

---

# T

## Ticket

A digital event admission record containing a unique QR code.

---

## Trust Score

A future internal metric representing the reliability of businesses based on successful transactions, disputes, and customer satisfaction.

---

# U

## University

The institution a student belongs to.

Version 1 associates users with a university but does not classify them by department or academic level.

---

## User

Any registered account on CartFlow.

User categories:

- Student
- Business
- Administrator

---

# W

## Wallet

A potential future feature allowing users and businesses to store funds within CartFlow.

Version 1 does not include wallets.

---

## Webhook

A callback mechanism allowing external services (such as payment providers) to notify CartFlow of completed events.

---

# Recommendation

This glossary should be treated as the **single source of truth** for terminology across the entire project.

Whenever a new feature introduces a new concept (for example, "Campus Ambassador", "Referral Code", or "Business Verification"), it should be added here immediately. Keeping the glossary current ensures that documentation, UI labels, API documentation, and code all use consistent language, reducing misunderstandings as the project grows.

---

# End of Document