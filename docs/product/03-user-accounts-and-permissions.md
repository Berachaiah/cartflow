# 03. User Accounts and Permissions

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 15, 2026

---

# 1. Purpose

This document defines the complete account system used throughout CartFlow.

It specifies:

- Account types
- Roles
- Permissions
- Registration
- Profiles
- Privacy
- Authentication
- Authorization
- Account lifecycle

Every feature within CartFlow relies on the permissions defined in this document.

---

# 2. Account Types and the Capability Model

CartFlow separates **identity** (the account type, chosen at signup) from
**capability** (what the account is allowed to do). This is the core of the
account system and the reason a student can begin selling without becoming a
different kind of account.

## Identity: account type

Every account has exactly one account type. It is descriptive and does not flip
on its own.

- **Student** — a user with a university affiliation. The default campus persona.
- **Individual** — a personal account with no university affiliation. Carries
  CartFlow beyond campuses to the wider community.
- **Business** — a standalone business ("brand").

## Capability: seller

Selling is a **capability** (`is_seller`), not an account type. Any account that
owns a business has it, regardless of identity. The seller capability unlocks
product management, events, orders, payouts, and the Business Hub.

- A Student or Individual gains it via **"Start selling"**, which creates the
  business they own and turns the capability on — **without changing their
  account type**. A student who starts a business is still a Student.
- A Business account has the capability from creation.

Source of truth is ownership: an `organizations` row whose `owner_user_id` is
the user. `is_seller` on the user is a denormalized mirror kept in sync by the
signup and upgrade services, used for cheap view-gating.

## Administrator

Administrators manage the platform. They are created internally; users cannot
register as administrators.

---

# 3. What Gates on What

Access is decided by capability, not by a rigid type hierarchy:

- **Social + buying** (feed, stories, posts, follows, purchases, tickets,
  messaging) — every account.
- **Selling + Business Hub** (products, inventory, events, payouts, analytics) —
  any account with the **seller capability**.
- **Platform administration** — administrators only.

Administrators have unrestricted platform access.

---

# 4. Registration

Users begin registration by choosing a persona, which selects the identity type
and whether the seller capability is on at creation:

- **Student** — Student identity, not a seller.
- **Individual** — Individual identity, not a seller.
- **Student + Business** — Student identity, seller on (keeps the school).
- **Business** — Business identity, seller on.

This choice determines the rest of the form.

---

# 5. Registration Fields

All personas share: **Full Name**, **Username**, **Email**, **Password**
(password is omitted on the Google path — the account is created passwordless
and pre-verified).

Persona-specific additions:

| Persona | Adds |
|---|---|
| Student | School |
| Individual | — |
| Student + Business | School **and** Business Name + State |
| Business | Business Name + State |

No street address is collected at registration. A seller configures pickup and
delivery details later in the Business Hub. Full authentication and onboarding
detail lives in document 05.

---

# 6. Google Sign-In

Version 1 supports Google Sign-In alongside email + password. A returning Google
user is logged straight in; a new Google user chooses a username and persona in
a short finish-signup step, then the account is created passwordless with the
Google-verified email already verified. Google users are matched on `google_sub`
first, then email.

---

# 7. Universities

The university field is selected from a predefined database.

Users cannot manually enter university names.

This ensures consistent analytics and search.

Future updates may allow administrators to add institutions.

---

# 8. Username Rules

Usernames must:

- be unique
- contain only letters
- numbers
- underscores
- periods

Maximum length:

30 characters

Minimum length:

3 characters

Usernames are case-insensitive.

---

# 9. Profile URLs

Every profile receives a permanent URL.

Example

```
/@berachaiah

/@royalfragrance
```

Changing usernames automatically redirects old profile links.

---

# 10. Profile Types

Student profiles contain:

- Profile photo
- Name
- Username
- Bio
- University
- Posts
- Stories
- Followers
- Following
- Liked
- Saved
- Reposts

---

Business profiles additionally contain:

- Business logo
- Business category
- Website
- Products
- Events
- Reviews
- Shop button
- Business status
- Delivery coverage

---

# 11. Business Status

Businesses may indicate current availability.

Examples

Open

Closed

Holiday Mode

Temporarily Unavailable

Vacation

Students always see current status.

---

# 12. Authentication

Version 1 supports:

- Email + Password
- Google Sign-In

Passwords are securely hashed (Argon2). Plain-text passwords are never stored.
Accounts created through Google are passwordless — `password_hash` is null and
authentication happens through Google — so a null password can never be used to
log in.

---

# 13. Sessions

After authentication the server issues a secure session cookie.

Sessions expire after inactivity.

Logout invalidates the session immediately.

---

# 14. Authorization

Every request verifies:

- Authentication
- User role
- Permission

Unauthorized actions return HTTP 403.

Unauthenticated requests return HTTP 401.

---

# 15. Permissions Matrix

Permissions are grouped by capability, not by account type. A student and an
individual have the same base permissions; either becomes a seller by owning a
business.

## Everyone (Student, Individual, Business)

Can:

- Create posts
- Create stories
- Like
- Save
- Repost
- Comment
- Share
- Follow users
- Purchase products
- Buy tickets
- Send message requests

## Sellers (any account that owns a business)

Can additionally:

- Create products
- Manage products
- Manage inventory
- Create discounts
- Create events
- View analytics
- Receive payouts
- Process orders
- Access the Business Hub

A non-seller (a Student or Individual who hasn't started selling) has none of
the seller permissions until they tap **"Start selling."**

---

## Administrators

Can:

- View all users
- Suspend accounts
- Delete content
- Manage businesses
- View analytics
- Manage payments
- Release escrow manually
- Review reports
- View audit logs

---

# 16. Privacy

Users may configure:

Public Profile

Private Profile (future)

Message Requests

Activity Visibility

Story Visibility

Profile visibility defaults to Public.

---

# 17. Blocking

Users may block other users.

Blocked users cannot:

- Follow
- Message
- View private content
- Mention

Blocking is mutual.

---

# 18. Reporting

Users may report:

Posts

Stories

Messages

Products

Businesses

Events

Profiles

Reports enter the moderation queue.

---

# 19. Account Deletion

Users may request account deletion.

Deletion follows soft-delete rules.

Content is retained temporarily for recovery.

Permanent deletion occurs after the retention period.

---

# 20. Account Suspension

Administrators may suspend:

Students

Businesses

Reasons include:

Fraud

Spam

Harassment

Illegal content

Repeated policy violations

Suspended users cannot log in.

---

# 21. Start Selling (capability upgrade)

A Student or Individual can begin selling at any time via **"Start selling."**
This:

- creates a business the user owns (`owner_user_id`),
- turns on the seller capability (`is_seller`),
- **keeps the account type unchanged** — a student stays a student.

Existing followers, posts, stories, and messages remain intact. The Business Hub
and seller features become available immediately; no manual approval is required
in Version 1.

There is no reverse "convert back" flow in V1: selling is a capability that is
turned on, not an identity swap. Closing a business (hiding the storefront and
making products unavailable) is handled in the Business Hub.

---

# 22. Graduation

A student may self-mark as **graduated** (a nullable `graduated_at` timestamp,
toggled in the profile / Business Hub).

- It is purely informational. **There is no alumni or graduate badge anywhere**,
  and login is never gated on it.
- Its one functional effect: if the graduating user owns a business, they are
  prompted to review that business's **pickup address**, since a campus pickup
  point likely no longer applies.

---

# 23. Notifications

Users receive notifications for:

Login

Password changes

Email updates

Account suspension

Business approval (future)

Starting to sell

---

# 24. Security Requirements

Passwords must satisfy minimum complexity.

Sessions use Secure and HttpOnly cookies.

CSRF protection is enabled.

Rate limiting protects authentication endpoints.

Repeated failed logins trigger temporary lockouts.

---

# 25. Audit Logging

The system records:

Account creation

Login

Logout

Password changes

Email changes

Starting to sell

Account deletion

Administrative actions

Audit logs are immutable.

---

# 26. Database Relationships

Users relate to:

Profiles

Posts

Stories

Comments

Likes

Reposts

Messages

Orders

Tickets

Businesses

Notifications

Activities

Settings

---

# 27. API Endpoints

All auth routes are under the `/api/auth` prefix.

Authentication

POST /api/auth/signup            (unified — persona in body)

POST /api/auth/signup/student    (back-compat alias)

POST /api/auth/login

POST /api/auth/logout

GET  /api/auth/google/login

GET  /api/auth/google/callback

POST /api/auth/forgot-password

POST /api/auth/verify-reset-otp

POST /api/auth/reset-password

POST /api/auth/verify-email

POST /api/auth/resend-verification

---

Seller capability & graduation

POST /api/auth/business/upgrade   ("Start selling")

POST /api/auth/graduation

---

Users

GET /api/auth/me

GET /api/auth/check-username

GET /api/users/{username}

PATCH /api/users/me

DELETE /api/users/me

---

# 28. Future Enhancements

Future versions may introduce:

Apple Login

Multi-factor Authentication

Business verification badges

Student verification

Business teams

Organization accounts

Role-based business staff

---

# End of Document