# 23. API Architecture

# Overview

CartFlow exposes a versioned REST API designed around business domains rather than database tables.

Each domain is represented by its own API module, keeping endpoints organized, scalable, and easy to maintain.

All endpoints return JSON unless otherwise specified.

---

# API Versioning

Current Version

```
/api/v1/
```

Future versions will be introduced without breaking existing client applications.

Examples

```
/api/v1/
/api/v2/
```

---

# Authentication

CartFlow uses secure server-side sessions.

Authentication is performed using HttpOnly secure cookies.

Cookies are automatically included with authenticated requests.

Authentication Endpoints

```
POST   /auth/signup
POST   /auth/login
POST   /auth/logout
GET    /auth/me
POST   /auth/verify-email
POST   /auth/resend-verification
POST   /auth/forgot-password
POST   /auth/reset-password
```

---

# Organization API

The Organization API manages all organizations available on CartFlow.

Although V1 only exposes universities to users, the backend is designed to support additional organization groups and organization types.

## Organization Groups

```
GET /organization-groups
```

Returns every available organization group.

Examples:

- Education
- Business
- Government
- Non-Profit
- Other

---

## Organization Types

```
GET /organization-types
```

Supports filtering by organization group.

Example

```
GET /organization-types?group=education
```

Returns

- University
- Polytechnic
- College
- Monotechnic
- Training Institute

---

## Organizations

Search organizations

```
GET /organizations/search
```

Supported search features

- Name
- Short name
- Alias
- Abbreviation
- Fuzzy search

Autocomplete returns a maximum of five ranked suggestions.

---

Get Organization Directory

```
GET /organizations
```

Supports

- Search
- Pagination
- Country
- State
- Organization Group
- Organization Type

Example

```
GET /organizations?page=1&type=university
```

---

Organization Details

```
GET /organizations/{id}
```

---

# Organization Requests

Create Organization Request

```
POST /organizations/request
```

Body

```
{
    "name": "",
    "country": "",
    "state": "",
    "organization_type": "university"
}
```

---

Organization Request Status

```
GET /organizations/request/{id}
```

---

# Signup Requests

When an organization does not yet exist, CartFlow stores the user's signup information until the organization has been reviewed.

Create Signup Request

```
POST /signup-request
```

Status

```
GET /signup-request/{id}
```

---

# Feed

```
GET    /feed
POST   /posts
PATCH  /posts/{id}
DELETE /posts/{id}
```

---

# Products

```
GET    /products
GET    /products/{id}
POST   /products
PATCH  /products/{id}
DELETE /products/{id}
```

---

# Orders

```
POST /checkout

GET /orders

GET /orders/{id}
```

---

# Order Support

Order Support is used only between the customer and business owner.

Create Conversation

```
POST /orders/{id}/support
```

Get Conversation

```
GET /orders/{id}/support
```

Messages

```
POST /orders/{id}/support/messages
```

Close Conversation

```
POST /orders/{id}/support/close
```

Escalate

```
POST /orders/{id}/support/escalate
```

---

# Refunds

Customer Request Refund

```
POST /orders/{id}/refund/request
```

Business Agree

```
POST /orders/{id}/refund/agree
```

Customer Confirm Return

```
POST /orders/{id}/refund/customer-confirm
```

Business Confirm Receipt

```
POST /orders/{id}/refund/business-confirm
```

Refund Status

```
GET /orders/{id}/refund
```

---

# CartFlow Support

Create Ticket

```
POST /support
```

List Tickets

```
GET /support
```

Ticket Details

```
GET /support/{id}
```

Messages

```
POST /support/{id}/messages
```

Close Ticket

```
POST /support/{id}/close
```

---

# Notifications

```
GET /notifications

PATCH /notifications/{id}/read

PATCH /notifications/read-all
```

---

# Administration

Organization Requests

```
GET /admin/organization-requests

PATCH /admin/organization-requests/{id}
```

Organizations

```
GET /admin/organizations

POST /admin/organizations

PATCH /admin/organizations/{id}

DELETE /admin/organizations/{id}
```

Users

```
GET /admin/users

PATCH /admin/users/{id}
```

Products

```
GET /admin/products
```

Orders

```
GET /admin/orders
```

Support

```
GET /admin/support
```

Analytics

```
GET /admin/analytics
```

---

# Response Format

Successful responses

```json
{
    "success": true,
    "data": {}
}
```

Errors

```json
{
    "success": false,
    "error": {
        "code": "",
        "message": ""
    }
}
```

---

# API Design Principles

Every endpoint should:

- Follow REST conventions.
- Return predictable response structures.
- Validate all incoming data.
- Return appropriate HTTP status codes.
- Be independently testable.
- Remain backwards compatible within the same API version.

---

# Recommendation

## Resource-Oriented APIs

APIs should represent business resources rather than implementation details.

Examples

```
/organizations
```

instead of

```
/universities
```

```
/support
```

instead of

```
/tickets
```

```
/auth
```

instead of

```
/users/login
```

Although CartFlow V1 primarily exposes universities to users, the backend APIs should remain organization-oriented. This allows future support for businesses, government organizations, non-profit organizations, and additional organization types without requiring breaking API changes.