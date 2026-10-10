# 17. Events and Ticketing

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

The Events module enables businesses to create, manage, promote, and sell tickets for events directly on CartFlow.

Unlike standalone event platforms, events integrate seamlessly with the social feed, business profiles, discovery features, and the commerce system.

Event organizers create events under their Business Account, allowing one business to manage multiple events.

---

# 2. Objectives

The Events module should:

- Allow businesses to host multiple events.
- Sell tickets securely.
- Deliver tickets instantly.
- Prevent ticket fraud.
- Support QR-based check-in.
- Integrate events into the social experience.
- Generate revenue through platform commission.

---

# 3. Business Model

Events are treated as business assets.

Example:

Business:

```
Bells Dinners
```

Events:

- BUSA Dinner 2026
- BUESA Dinner 2026
- Engineering Dinner 2026

A single business may own unlimited events.

---

# 4. Event Creation

Businesses can create events from the Business Hub.

Required fields:

- Event Name
- Banner Image
- Description
- Date
- Start Time
- End Time
- Venue
- University
- Ticket Price
- Ticket Quantity

Optional fields:

- Dress Code
- Guest Speakers
- Sponsors
- External Website
- Terms & Conditions

---

# 5. Event Status

Events may be:

- Draft
- Published
- Sold Out
- Completed
- Cancelled

Only Published events are visible to users.

---

# 6. Event Page

The Event Details page displays:

- Banner
- Event Name
- Organizer
- Date
- Time
- Venue
- Description
- Ticket Price
- Tickets Remaining
- Share Button
- Purchase Ticket

---

# 7. Event Feed Integration

Events can be promoted through feed posts.

Businesses may create:

- Launch posts
- Countdown posts
- Reminder posts
- Behind-the-scenes posts

Event posts behave like normal feed posts and participate in the feed ranking algorithm.

---

# 8. Event Stories

Businesses may share event Stories.

Examples:

- Countdown
- Ticket sales
- Behind the scenes
- Venue setup
- Guest announcements

Stories disappear after 24 hours.

---

# 9. Ticket Types

Version 1 supports a single ticket type per event.

Future versions may support:

- VIP
- Early Bird
- Student
- Regular
- Group Tickets

---

# 10. Ticket Purchase

Customers choose:

Quantity

↓

Checkout

↓

Payment

↓

Ticket Created

↓

Email Sent

↓

Order Recorded

---

# 11. Multiple Tickets

Customers may purchase multiple tickets in one transaction.

Each ticket receives:

- Unique Ticket ID
- Unique QR Code
- Unique Barcode (optional)
- Individual Owner Record

---

# 12. Ticket Holder Details

For every ticket purchased, buyers provide:

- Full Name
- Email Address
- Phone Number (optional)

Example:

3 tickets require details for all 3 attendees.

This prevents ticket duplication and simplifies entry.

---

# 13. Ticket Delivery

After successful payment:

Tickets are:

- Emailed
- Available inside the Order Details page

Each ticket contains:

- QR Code
- Ticket Number
- Event Name
- Date
- Venue
- Organizer

---

# 14. QR Code Validation

Each ticket contains a unique QR code.

Once scanned:

The ticket status changes to:

```
Used
```

Used tickets cannot be scanned again.

---

# 15. Entry Validation Interface

CartFlow provides an Event Check-in interface for event staff.

Staff can:

- Scan QR codes
- Search by Ticket Number
- Search by Attendee Name
- View validation status
- Mark attendance

This interface is optimized for mobile devices.

---

# 16. Ticket Status

Possible states:

- Active
- Used
- Cancelled
- Refunded

Status updates occur immediately after scanning or refunds.

---

# 17. Entry Feedback

Successful scan:

```
✅ Valid Ticket

Welcome!
```

Duplicate scan:

```
❌ Ticket Already Used
```

Invalid QR:

```
❌ Invalid Ticket
```

---

# 18. Event Analytics

Businesses can view:

- Ticket Sales
- Revenue
- Tickets Remaining
- Check-ins
- Attendance Rate
- Refunds
- Conversion Rate

---

# 19. Notifications

Customers receive:

- Ticket Purchase Confirmation
- Ticket Email Sent
- Event Reminder (24 hours before)
- Event Reminder (2 hours before)
- Event Updates
- Event Cancellation

Businesses receive:

- Ticket Sold
- Event Published
- Event Sold Out

---

# 20. Sharing

Events support:

Internal Share

- Direct Messages

External Share

- Copy Link
- WhatsApp
- Telegram
- Facebook
- X
- Instagram
- System Share Sheet

Every event has a permanent public URL.

---

# 21. Search & Discovery

Events appear in:

- Search
- Discover
- Business Profile
- Feed Posts
- Shared Links

The recommendation system considers:

- University
- Engagement
- Popularity
- Following
- Event date

---

# 22. Reporting

Users may report:

- Scam
- Incorrect Information
- Duplicate Event
- Inappropriate Content

Reported events enter the moderation queue.

---

# 23. Database Entities

Primary tables:

- events
- event_tickets
- event_orders
- ticket_holders
- ticket_scans
- event_checkins

---

# 24. API Endpoints

GET /api/events

GET /api/events/{slug}

POST /api/events

PUT /api/events/{id}

DELETE /api/events/{id}

POST /api/events/{id}/purchase

POST /api/events/checkin

GET /api/events/{id}/analytics

---

# 25. Performance

The Events module should:

- Load banners efficiently.
- Cache event pages.
- Generate QR codes quickly.
- Validate tickets in near real time.
- Handle large check-in volumes.

---

# 26. Future Enhancements

Potential future additions:

- Multiple ticket tiers
- Seating plans
- Waitlists
- Event sponsorships
- Event livestreams
- Calendar integration
- Ticket transfers
- Promotional codes

---

# 27. Summary

The Events and Ticketing module transforms CartFlow into more than a social commerce platform.

By combining social promotion, secure ticket sales, QR-based entry, and business analytics, it enables organizers to manage events efficiently while providing attendees with a seamless purchasing and check-in experience.

---

# Implementation Status — as built (August 16, 2026)

**Not built — this is Milestone 2**, specced and scheduled after the content and
payments work. No `events`, `event_categories`, `event_media`,
`event_ticket_types`, `event_tickets` or `event_checkins` tables exist; there is no
`/events` route and no scanner route.

Where events appear in the app today, and what each one honestly says:

- **Discover** (`app/templates/discover.html`) renders an "Upcoming events" section
  from placeholder data — the §4 layout, no rows behind it.
- **Home** (`app/templates/home.html`) has a promoted-event card whose *Get Tickets*
  button toasts "Ticketing — coming soon".
- **Business Hub** (`app/templates/dashboard.html`) has the Events panel from doc 16
  §4 as an empty state naming what it waits on, including ticket sales.
- **The `+` create sheet** (`app/templates/base.html`) lists Event as **Milestone 2
  (doc 17)**, so tapping `+` tells you the truth about where the feature is.

**Blocking dependencies, in order:** payments + escrow (doc 15) before tickets can be
sold; media (Cloudinary) before covers and the post-event gallery; notifications
(doc 11) for reminders, cancellations and reschedules. The QR check-in flow itself is
self-contained once `event_tickets` exists — scan → verify belongs-to-this-event and
`VALID` → mark `USED` → write an `event_checkins` row.

**Design decision to keep:** an Event is **not** a feed post. It has its own
lifecycle, ticketing, attendees and gallery, and can be *promoted* through the feed —
so it gets its own tables rather than a `type` column on posts. Create/manage stays
gated on owning a business.

---

# End of Document