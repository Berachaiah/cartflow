# 01. Product Overview

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 15, 2026

---

# 1. Introduction

CartFlow is a mobile-first social commerce platform designed to simplify buying, selling, discovering businesses, and managing events within university communities.

Unlike traditional marketplaces that focus only on commerce, CartFlow combines social networking, digital commerce, event ticketing, messaging, and business management into a unified ecosystem.

Students can discover businesses through an engaging social feed, interact with friends, purchase products, attend events, and communicate without leaving the platform.

Businesses can showcase products, build an audience, manage orders, sell tickets, receive payments securely, and operate from a centralized Business Hub.

CartFlow is designed to become the digital marketplace and community platform for campuses.

---

# 2. Mission Statement

To make buying, selling, and discovering businesses within university communities simple, trustworthy, and social.

---

# 3. Vision Statement

To become Africa's leading social commerce ecosystem for educational institutions and local communities by combining commerce, social networking, and digital business management into one seamless experience.

---

# 4. Product Philosophy

CartFlow is built around six core principles.

## 4.1 Mobile First

Most users access the internet using smartphones.

Every screen, interaction, and workflow is designed primarily for mobile devices before desktop adaptations.

---

## 4.2 Social First

People discover products through people.

Commerce should naturally emerge from social interactions rather than isolated marketplace listings.

Businesses should build audiences, not just product catalogs.

---

## 4.3 Trust

Every transaction should feel safe.

Customers should have confidence that payments are protected until orders are completed.

Businesses should know they will receive payment after fulfilling their obligations.

---

## 4.4 Simplicity

Complex systems create friction.

Common actions such as:

- buying a product
- creating a post
- replying to messages
- adding inventory
- updating business information

should require as few steps as possible.

---

## 4.5 Transparency

Users should always understand:

- where their money is
- the status of their orders
- inventory availability
- event ticket status
- delivery progress

No hidden processes should exist.

---

## 4.6 Scalability

Although CartFlow launches for universities, every architectural decision should support future expansion into broader communities without requiring major redesigns.

---

# 5. Target Audience

CartFlow primarily serves university communities.

Primary users include:

- Students
- Campus businesses
- Student entrepreneurs
- Event organizers

Secondary users include:

- Alumni
- Visitors
- External customers purchasing from campus businesses

Future expansion may include:

- Colleges
- Polytechnics
- Local businesses
- Corporate communities

---

# 6. User Types

CartFlow separates **who a user is** (identity) from **what a user can do**
(capability). This split is what lets the platform grow past university students
without a redesign.

**Identity** is the account type chosen at signup — descriptive, and it does not
change on its own:

- **Student** — joined with a university affiliation.
- **Individual** — a personal, non-university account.
- **Business** — a standalone business ("brand").

**Selling is a capability, not an identity.** Any account that owns a business
gains the seller capability (`is_seller`) and, with it, product management,
events, orders, payouts, and the Business Hub. A student or an individual can
start selling at any time via **"Start selling"** — this creates the business
they own and turns on the capability while **keeping their account type**. A
student who starts a business is still a student; they are now also a seller.

## Student

Students can:

- Follow users
- Create posts
- Create stories
- Browse businesses
- Purchase products
- Attend events
- Send messages
- Save posts
- Like posts
- Repost content

A student who has not started selling has no products, Business Hub, or
storefront — those appear the moment they start selling (see above). Stories,
posts, and all social actions are available to everyone.

---

## Individual

An individual is a personal account with no university affiliation. Individuals
have the same social and buying capabilities as students, and can likewise
**start selling** to become a seller. This is the persona that carries CartFlow
beyond campuses to the wider local community.

---

## Seller (capability)

Any account — student, individual, or business — that owns a business is a
seller. Sellers gain, on top of their base capabilities:

- Business profile
- Product management
- Inventory management
- Order management
- Business analytics
- Event creation
- Discount management
- Business operations dashboard
- Payment settings
- Business verification (future)

A business the user owns may represent:

- Student brands
- Service providers
- Restaurants
- Fashion vendors
- Event companies

## Graduation

A student can self-mark as **graduated**. This is purely informational — there
is no badge, and login is never gated on it. Its one effect: a graduated user
who owns a business is prompted to review that business's pickup address, since
a campus pickup point likely no longer applies.

---

## Administrator

Administrators manage the platform through the Admin Panel.

Responsibilities include:

- User management
- Business management
- Product moderation
- Event moderation
- Payment monitoring
- Escrow management
- Analytics
- Error monitoring
- System configuration

---

# 7. Core Features

CartFlow consists of several integrated modules.

## Social

- Home Feed
- Stories
- Comments
- Likes
- Saves
- Reposts
- Sharing
- Profiles

---

## Commerce

- Shop
- Products
- Inventory
- Cart
- Checkout
- Orders
- Discounts
- Delivery

---

## Business

- Business Hub
- Product Management
- Inventory Tracking
- Order Processing
- Business Analytics
- Business Settings

---

## Events

- Event creation
- Ticket sales
- QR tickets
- Event check-in
- Ticket validation
- Attendance management

---

## Messaging

- Direct messages
- Message requests
- Media sharing
- Read receipts
- Activity inbox

---

## Payments

- Secure checkout
- Escrow
- Automatic releases
- Manual intervention
- Payout management
- Transaction history

---

# 8. Problems CartFlow Solves

Before CartFlow:

Businesses rely on scattered platforms:

- WhatsApp
- Instagram
- Bank transfers
- Google Forms
- Manual inventory
- Paper tickets

Customers struggle to:

- Discover businesses
- Verify sellers
- Track orders
- Find campus events
- Purchase tickets securely

Event organizers manually verify attendees.

Payments are difficult to trust.

---

# 9. The CartFlow Solution

CartFlow centralizes the entire experience.

Businesses receive:

- Audience growth
- Online storefront
- Inventory management
- Secure payments
- Event management

Students receive:

- Better discovery
- Easier purchasing
- Safer payments
- Campus community

Administrators receive:

- Full operational visibility
- Analytics
- Moderation tools

---

# 10. Competitive Advantages

CartFlow differentiates itself through:

- Social commerce integration
- Campus-focused ecosystem
- Escrow-based payments
- Integrated ticketing
- Business Hub
- Native event management
- Recommendation engine
- Mobile-first experience

Rather than replacing social interaction, CartFlow uses social engagement to drive commerce.

---

# 11. Success Metrics

The success of CartFlow will be measured through:

## Marketplace

- Monthly Gross Merchandise Value (GMV)
- Total orders
- Average order value
- Conversion rate

---

## Social

- Daily Active Users (DAU)
- Monthly Active Users (MAU)
- Posts created
- Stories created
- Engagement rate

---

## Business

- Active businesses
- Products listed
- Orders fulfilled
- Business retention

---

## Events

- Events created
- Tickets sold
- QR check-ins
- Event attendance

---

## Platform

- User retention
- Average session duration
- Crash-free sessions
- API response time
- Payment success rate

---

# 12. Product Scope

Version 1 includes:

- Social feed
- Stories
- Shop
- Cart
- Checkout
- Orders
- Escrow
- Messaging
- Business Hub
- Events
- Admin Panel
- Recommendation engine
- Analytics

Features intentionally excluded from Version 1 include:

- Native mobile applications
- Business teams
- Public API platform
- Advertising platform
- AI-powered recommendations
- Multi-language support

These are planned for future releases.

---

# 13. Long-Term Vision

CartFlow is not intended to remain a university marketplace indefinitely.

The long-term objective is to evolve into a scalable social commerce platform capable of serving educational institutions, communities, and local businesses across multiple regions while maintaining the simplicity and trust established in Version 1.

Every feature introduced in V1 should support this long-term direction.

---

# End of Document