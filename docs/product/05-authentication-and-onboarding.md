# 05. Authentication and Onboarding

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 15, 2026

---

# 1. Purpose

This document defines the complete authentication and onboarding experience for CartFlow.

It specifies:

- User registration
- Business registration
- Login
- Logout
- Password recovery
- Session management
- Onboarding
- Email verification
- Account security
- Authentication APIs
- Authentication database requirements

---

# 2. Authentication Principles

Authentication should be:

- Fast
- Secure
- Familiar
- Mobile-first
- Easy to recover
- Resistant to abuse

Users should be able to create an account in under two minutes.

---

# 3. Authentication Methods (V1)

Version 1 supports:

✓ Email + Password

✓ Google Sign-In (OpenID Connect)

Future versions may support:

- Apple Sign-In
- Microsoft Sign-In
- Passkeys
- Multi-factor Authentication (MFA)

Google Sign-In is offered on both the login and signup pages when the server is
configured with Google OAuth credentials; the button is hidden otherwise so a
non-functional control never ships. A returning Google user is logged straight
in; a new Google user is routed to a short **finish-signup** step to choose a
username and persona before the account is created (see Section 4).

---

# 4. Registration Flow

Users begin by choosing a persona, which drives the rest of the form.

```
Welcome

↓

Create Account

↓

Choose Persona
(Student / Individual / Student + Business / Business)

↓

Registration Form
(persona-specific fields)

↓

Account Created

↓

Login

↓

Home Feed
```

Google path: choosing "Continue with Google" on signup sends the user to Google,
then back to a **finish-signup** step that collects username + persona (+ school
if the persona needs one). The account is then created passwordless, with the
Google-verified email pre-verified. Returning Google users skip this and are
logged straight in.

---

# 5. Personas and Account Types

Signup offers four personas. A persona is not the same as the stored account
type — it selects the identity type **and** whether the seller capability is
turned on at creation.

## Student

A university student. Requires a school (chosen from the list). Not a seller by
default; can start selling later.

## Individual

A personal, non-university account. No organization. Not a seller by default;
can start selling later.

## Student + Business

A student who also sells. Keeps the university affiliation **and** owns a
business created at signup. Account type stays Student; the seller capability is
on. This is the persona that graduation + pickup-address logic applies to.

## Business

A standalone business ("brand"). Account type is Business, seller capability on,
no school affiliation.

> Selling is a capability (`is_seller`), not a separate identity. A Student or
> Individual can gain it any time via **"Start selling"** without changing
> account type. See document 03 for the full identity-vs-capability model.

Business accounts inherit all buying and social capabilities.

---

# 6. Registration Fields by Persona

All personas share these base fields:

- Full Name
- Username
- Email Address
- Password (optional on the Google path — see below)

Persona-specific fields are added on top:

| Persona | Adds |
|---|---|
| Student | School (from the list) |
| Individual | — (nothing extra) |
| Student + Business | School **and** Business Name + State |
| Business | Business Name + State |

On the Google finish-signup path the password is omitted (the account is
created passwordless and pre-verified); exactly one of password / Google token
is present on any signup.

---

Validation Rules

Email must be unique.

Username must be unique (see rules below).

Password, when supplied, is at least 8 characters.

A school, when required, must resolve against the organization database. If a
student types a school that isn't found, the signup is accepted and the school
is queued for review rather than blocking the account.

Business personas require both a Business Name and a State.

---

# 7. School Selection

Student and Student + Business personas choose a school from a predefined,
searchable list (the university typeahead). Manual free-text entry is not the
primary path; if a school is missing, the typed name is captured and queued for
admin review so the user is never hard-blocked.

The Individual and Business personas have no school field.

A business's operating details (pickup location, delivery coverage, delivery
options) are configured later in the Business Hub, not at signup.

---

# 8. Why a Predefined School List

Schools are chosen from a curated list rather than typed freely because it
keeps data consistent and powers search, analytics, and recommendations
(e.g. "events at your university"). The list covers recognized Nigerian
universities and is administrator-maintainable. The one escape hatch is the
review queue described in Section 7, so a genuinely missing school never blocks
a signup.

---

# 9. Addresses

No street address is collected at signup — it is not a registration field for
any persona.

A **business** configures its operating details later in the Business Hub:
pickup location, delivery coverage, and delivery options. These are editable at
any time and are not restricted to campus — a business may operate on campus,
off campus, or nationwide. Graduation prompts a seller to revisit the pickup
address, since a campus pickup point may no longer apply.

---

# 10. Username Rules

Usernames:

- Minimum: 3 characters
- Maximum: 30 characters

Allowed:

- Letters
- Numbers
- Underscores
- Periods

Examples:

```
berachaiah

royal_fragrance

campus.foods

jane123
```

Not allowed:

```
Spaces

Special symbols

Duplicate usernames
```

---

# 11. Password Rules

Minimum length:

8 characters

Recommended:

- Uppercase letter
- Lowercase letter
- Number

Future versions may require stronger password policies.

Passwords are never stored in plaintext.

---

# 12. Login

Users log in using:

- Email
- Password

Successful login creates a secure authenticated session.

---

# 13. Session Management

Authentication uses secure HTTP-only cookies.

Sessions automatically expire after prolonged inactivity.

Users can log out at any time.

Logging out immediately invalidates the active session.

---

# 14. Forgot Password

Flow:

```
Forgot Password

↓

Enter Email

↓

Receive Reset Email

↓

Open Link

↓

Create New Password

↓

Login
```

Password reset links expire after a configurable period.

Links can only be used once.

---

# 15. Email Verification

Version 1 does not require email verification before using the platform.

However, verification emails may still be sent for improved account recovery and trust.

Future versions may require mandatory verification.

---

# 16. Logout

Users can log out from:

- Settings
- Profile menu

Logging out removes the active session.

---

# 17. Seller Onboarding

Whenever an account first gains the seller capability — whether at signup (the
Business or Student + Business personas) or later via **"Start selling"** — it
is guided through a short setup process.

Recommended steps:

1. Upload logo
2. Add business bio
3. Select business category
4. Add pickup location
5. Configure delivery coverage
6. Choose delivery options
7. Add first product

These steps may be skipped and completed later in the Business Hub. No manual
approval is required in Version 1; the Hub is available as soon as the
capability is on.

---

# 18. Student Onboarding

Students are encouraged to:

- Upload profile picture
- Add bio
- Follow suggested users
- Follow suggested businesses
- Create first post
- Explore the Shop

All steps are optional.

---

# 19. Login Security

The authentication system should include:

- Rate limiting
- Password hashing
- Secure cookies
- CSRF protection
- Brute-force protection
- Audit logging

---

# 20. Failed Login Attempts

Repeated failed login attempts temporarily lock the account.

Administrators can unlock accounts if necessary.

Users should receive a generic error message to prevent account enumeration.

---

# 21. Authentication Errors

Examples:

- Invalid email or password
- Username already exists
- Email already registered
- Invalid reset token
- Passwords do not match

Errors should be user-friendly and never expose internal implementation details.

---

# 22. Authentication Database Entities

Primary tables involved:

- users — includes `is_seller`, `google_sub` (unique, nullable), `graduated_at`
  (nullable), and a **nullable** `password_hash` (Google accounts are
  passwordless)
- organizations — includes `owner_user_id` (the seller who owns it) and
  `pickup_address`
- sessions
- password_reset_tokens (backs both the reset link and the 6-digit OTP)

Additional tables may be introduced as the platform evolves.

---

# 23. Authentication API Endpoints

All routes are under the `/api/auth` prefix.

## Registration

```
POST /api/auth/signup            (unified — persona in body)

POST /api/auth/signup/student    (back-compat alias for the student persona)
```

---

## Google Sign-In

```
GET  /api/auth/google/login?intent=login|signup

GET  /api/auth/google/callback
```

The callback verifies the signed state, identifies the Google user, then either
logs an existing user in (session cookie → home) or routes a new user to
finish-signup (`/signup?google=<token>`).

---

## Login

```
POST /api/auth/login
```

---

## Logout

```
POST /api/auth/logout
```

---

## Email Verification

```
POST /api/auth/verify-email

POST /api/auth/resend-verification
```

---

## Password Recovery

```
POST /api/auth/forgot-password     (emails a reset link AND a 6-digit code)

POST /api/auth/verify-reset-otp    (validate code/link without consuming it)

POST /api/auth/reset-password      (set new password via link token or code)
```

---

## Seller Capability & Graduation

```
POST /api/auth/business/upgrade    ("Start selling" — creates owned business)

POST /api/auth/graduation          (self-toggle; prompts pickup update if seller)
```

---

## Current User / Utilities

```
GET  /api/auth/me

GET  /api/auth/check-username
```

---

# 24. Future Enhancements

Potential future additions include:

- Apple Authentication
- Two-Factor Authentication (2FA)
- Passkeys
- Biometric login
- Device management
- Login history
- Trusted devices

---

# 25. Summary

The CartFlow authentication system prioritizes:

- Simplicity
- Security
- Fast onboarding
- Low friction
- Mobile-first usability

The registration process should require minimal effort while maintaining strong account security and providing a solid foundation for future authentication enhancements.

---

# End of Document