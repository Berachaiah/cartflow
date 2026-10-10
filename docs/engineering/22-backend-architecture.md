# 22. Backend Architecture

## Overview

CartFlow follows a modular, service-oriented backend architecture designed for scalability, maintainability, and future expansion.

Each business domain is isolated into its own service, ensuring clean separation of responsibilities, reusable business logic, and minimal coupling between modules.

Although CartFlow V1 primarily serves university students, the backend architecture is intentionally designed to support future expansion into additional educational institutions, businesses, government organizations, non-profit organizations, and other communities without requiring major architectural changes.

---

# Core Services

## Authentication Service

Responsible for:

- User registration
- Login
- Logout
- Email verification
- Password hashing (Argon2id)
- Session management
- Session validation
- Password reset
- Account status validation
- Security policies

---

## User Service

Responsible for:

- User profiles
- Username validation
- Profile updates
- Privacy settings
- Following
- Blocking
- User preferences
- Account management

---

## Organization Service

The Organization Service is responsible for managing every organization available on CartFlow.

Although CartFlow V1 launches with Nigerian universities only, the service is intentionally designed to support additional organization groups and organization types in future releases.

This service acts as the single source of truth for every organization-related operation throughout the platform.

---

## Organization Hierarchy

Organizations are grouped into high-level Organization Groups.

Each Organization Group contains one or more Organization Types.

Example hierarchy:

Organization

├── Education
│      ├── University
│      ├── Polytechnic
│      ├── College
│      ├── Monotechnic
│      └── Training Institute
│
├── Business
│      ├── SME
│      ├── Startup
│      ├── Enterprise
│      └── Local Business
│
├── Government
│
├── Non-Profit
│
└── Other

This hierarchy is configuration-driven and stored within the database rather than hardcoded into the application.

---

## Responsibilities

The Organization Service is responsible for:

- Organization autocomplete
- Intelligent search
- Fuzzy search
- Alias matching
- Abbreviation matching
- Organization directory
- Search filtering
- Pagination
- Organization selection
- Organization request management
- Organization approval workflow
- Organization administration

---

## Search Behaviour

Organization search supports:

- Official names
- Short names
- Common abbreviations
- Aliases
- Typographical errors (fuzzy search)

Autocomplete returns up to five ranked suggestions based on relevance.

When no organization matches:

The user is presented with:

- Browse our list of Universities
- Request a new University

Although the backend is organization-based, the frontend remains university-focused during V1.

---

## University Directory

CartFlow V1 provides a University Directory.

Features:

- Search
- Pagination (20 per page)
- Country filter
- State filter
- University selection

Selecting a university automatically populates the signup form.

---

## Organization Requests

If a university cannot be found:

The user may submit:

- University Name
- Country
- State / Province

Submitting the form creates:

- Organization Request
- Signup Request

The account is not created immediately.

Administrators may:

- Approve
- Reject
- Merge with an existing organization

Approving an organization automatically processes every pending signup request linked to that organization.

---

## Signup Request Service

Instead of rejecting signups for unsupported universities, CartFlow stores pending signup information until the requested university has been approved.

After approval:

- User account created
- Verification email sent
- Signup Request completed

---

## Feed Service

Responsible for:

- Feed ranking
- Posts
- Comments
- Likes
- Shares
- Recommendations

---

## Shop Service

Responsible for:

- Products
- Categories
- Inventory
- Discounts
- Business storefront

---

## Order Service

Responsible for:

- Checkout
- Orders
- Delivery
- Order lifecycle
- Order history

---

## Order Support Service

Provides direct communication between customers and business owners.

Supported categories include:

- Wrong Item
- Damaged Item
- Missing Item
- Delivery Issue
- Refund Request
- Return Request
- Other

Only the buyer and seller participate unless the conversation is escalated.

---

## Refund Service

Refund lifecycle:

Customer requests refund

↓

Business agrees

↓

Refund agreed

↓

Customer returns item

↓

Customer confirms return

↓

Business confirms receipt

↓

Flutterwave Refund API

↓

Refund completed

If either party disagrees:

↓

Escalate to CartFlow Support.

Refund eligibility depends on the product's refund policy.

---

## CartFlow Support Service

Handles issues that cannot be resolved between customers and business owners.

Examples:

- Payment Issues
- Login Problems
- Verification Issues
- Technical Support
- Bug Reports
- Account Appeals

CartFlow Support is separate from Order Support.

---

## Notification Service

Responsible for:

- Email
- Push Notifications
- In-App Notifications
- Activity Alerts

---

## Payment Service

Responsible for:

- Payment initialization
- Payment verification
- Escrow
- Settlement
- Refunds
- Commission calculation
- Flutterwave integration

The Payment Service abstracts payment providers from the rest of the platform, allowing additional providers to be added in the future without affecting business logic.

---

## Administration Service

Responsible for:

- User Management
- Organization Management
- Moderation
- Analytics
- Financial Monitoring
- Audit Logs
- Platform Configuration

---

# Architectural Principles

The backend follows these principles:

- Service-Oriented Architecture
- Separation of Concerns
- Single Source of Truth
- Provider Abstraction
- Reusable Business Logic
- Scalability
- Clean API Boundaries

Business logic should never live inside controllers or API routes.

Controllers should delegate work to their respective services.

---

# Recommendation

## Progressive User Experience

Although the backend is fully organization-driven, the frontend should only expose features relevant to the current stage of the platform.

Examples:

- CartFlow V1 displays only **University** during signup.
- Future releases may introduce additional Organization Groups and Organization Types.
- Backend architecture should always anticipate future expansion without exposing unnecessary complexity to users.

This approach allows CartFlow to remain simple for users while maintaining a scalable and future-ready architecture.