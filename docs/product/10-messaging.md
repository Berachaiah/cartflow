# 10. Messaging

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

Messaging enables users and businesses to communicate privately within CartFlow.

The messaging system supports customer inquiries, conversations between students, product discussions, event coordination, and sharing of content across the platform.

Messaging should remain lightweight, fast, and safe while preventing spam.

---

# 2. Objectives

Messaging should:

- Enable communication between users.
- Allow businesses to answer customer questions.
- Prevent spam.
- Support content sharing.
- Encourage meaningful conversations.
- Integrate naturally with commerce.

---

# 3. Who Can Message

Students can message:

- Students
- Businesses

Businesses can message:

- Students
- Businesses

Administrators do not participate in user conversations.

---

# 4. Conversation Types

Supported conversation types:

- Student ↔ Student
- Student ↔ Business
- Business ↔ Business

Group chats are excluded from Version 1.

---

# 5. Starting a Conversation

Users may start a conversation by:

- Visiting a profile
- Opening a business profile
- Sharing a product
- Sharing a post
- Sharing an event

---

# 6. Message Requests

When User A messages User B for the first time:

User A may send only **one** message.

User B receives a Message Request.

Until User B:

- Accepts the request
- Replies
- Deletes the request

User A cannot send another message.

Following back is optional and does not affect messaging permissions.

---

# 7. Message Request Actions

Recipients may:

- Accept
- Delete
- Block User
- Report User

Accepting moves the conversation into the main inbox.

---

# 8. Inbox

The inbox displays:

- Profile picture
- Name
- Last message
- Timestamp
- Unread badge

Conversations are sorted by recent activity.

---

# 9. Chat Screen

The chat interface includes:

Header

Messages

Shared Content

Image Picker

Emoji Button

Message Field

Send Button

---

# 10. Supported Message Types

Version 1 supports:

- Text
- Images
- Shared Posts
- Shared Products
- Shared Events
- Shared Profiles

Video messages are excluded from Version 1.

---

# 11. Image Sharing

Users may upload images.

Images are stored using Cloudinary.

Supported actions:

- View
- Download
- Zoom

Images are compressed before upload.

---

# 12. Shared Posts

Users may share feed posts directly into chats.

The recipient sees a preview card containing:

- Thumbnail
- Author
- Caption preview

Selecting the preview opens the original post.

---

# 13. Shared Products

Businesses and students may share products.

Product previews display:

- Image
- Product name
- Price
- Business

Selecting the preview opens the Product Details page.

---

# 14. Shared Events

Events may be shared.

The preview contains:

- Banner
- Event name
- Date
- Ticket status

Selecting the preview opens the Event Details page.

---

# 15. Shared Profiles

Users may share:

- Student profiles
- Business profiles

Shared profile cards include:

- Profile picture
- Display name
- Username

---

# 16. Emojis

Messaging supports standard Unicode emojis.

Custom emoji packs are not included in Version 1.

---

# 17. Read Receipts

Messages display:

✓ Sent

✓✓ Delivered

✓✓ Read

Read receipts update automatically.

---

# 18. Typing Indicator

When a user is typing:

"Typing..."

appears beneath the conversation header.

Typing indicators disappear after inactivity.

---

# 19. Online Status

Version 1 displays:

- Online
- Last Seen

Users may disable Last Seen in future versions.

---

# 20. Search

Users can search conversations by:

- Username
- Display name
- Business name

Message content search is reserved for future versions.

---

# 21. Notifications

Users receive push or in-app notifications for:

- New messages
- Message requests
- Accepted requests

Notification settings are configurable.

---

# 22. Blocking

Blocked users cannot:

- Send messages
- Send requests
- View conversation updates

Existing conversations become inaccessible.

---

# 23. Reporting

Users may report:

- Spam
- Harassment
- Fraud
- Abuse

Reports are submitted to administrators.

---

# 24. Performance

Chats should:

- Load quickly
- Paginate older messages
- Lazy-load images
- Cache recent conversations

---

# 25. Security

Messages are transmitted over HTTPS.

Only conversation participants can access message content.

All uploaded images undergo validation before storage.

---

# 26. Database Entities

Primary tables:

- conversations
- conversation_participants
- messages
- message_requests
- message_attachments
- message_reads

---

# 27. API Endpoints

GET /api/messages

GET /api/messages/{conversation_id}

POST /api/messages

POST /api/messages/request

POST /api/messages/accept

POST /api/messages/delete-request

POST /api/messages/block

---

# 28. Future Enhancements

Potential future additions:

- Group chats
- Voice messages
- Video messages
- Message reactions
- Polls
- Pinned messages
- Message search
- Voice & video calls
- Disappearing messages

---

# 29. Summary

The CartFlow messaging system is designed to facilitate secure and meaningful conversations while preventing spam.

By supporting content sharing, message requests, and lightweight media, messaging strengthens both the social and commercial aspects of the platform without introducing unnecessary complexity in Version 1.

---

# Implementation Status — as built (August 21, 2026)

**Messaging is built.** Real tables, a real inbox, a real thread, and a live
socket. What this section described as a specification through §16 is now running
code, and the differences between the two are recorded below — the spec was
written before the schema, so where they disagree the schema is the fact and the
reason for the divergence is worth having in writing.

## The schema is smaller than §26

Five tables, in `app/models/conversation.py` and `app/models/report.py`, created
by migrations `0009_messaging` and `0010_disappearing_messages`:
`conversations`, `conversation_participants`, `messages`, `user_blocks`,
`reports` — plus one column, `users.last_seen_at`, for presence.

Three of §26's seven are deliberately absent:

- **No `message_requests`.** §6's entire state machine is two columns on the
  conversation: `status` (PENDING / ACCEPTED / DECLINED) and `initiator_id`. A
  request *is* a conversation that has not been answered yet, so a separate table
  would be a second record of the same fact, kept in sync by hand, and the day
  the two disagree is the day a thread is both a request and an accepted
  conversation.
- **No `message_attachments`.** §11 allows one photo per message, so the
  attachment is one nullable `media_id` on the message row, pointing at the
  `media` table `0007` already created for avatars. A join table would model a
  cardinality the product does not have.
- **No `message_reads`.** One `last_read_at` per participant row, not a row per
  message per reader. §16 needs to answer "has this thread been seen up to
  here", which a timestamp answers; per-message receipts would insert a row for
  every message every reader opens, permanently, for messages that delete
  themselves after two days.

## The routes are addressed by handle where a conversation may not exist yet

Fourteen REST endpoints in `app/routers/messages.py`, plus `GET /ws/messages` in
`app/routers/ws.py`. §27's shape is close but its addressing is wrong in one
place, and it matters: the endpoints you reach *from a person* take a username —
`GET`/`POST /api/messages/threads/{username}`, `/blocks/{username}`,
`/reports/{username}` — because §6's first case, `none → PENDING`, has no
conversation id by definition. You know who you want to write to before there is
anything to name. The endpoints that act on a conversation that already exists
take its `public_id`: `/{public_id}/read`, `/accept`, `/decline`, `/archive`,
`/disappearing`.

`GET /api/messages` is the inbox, `?filter=all|unread|requests`, and it returns
**`has_more`** rather than leaving the client to infer it from
`len(items) == limit` — which is wrong on the page that divides evenly and offers
a "load more" that finds nothing. It costs a one-row over-fetch, not a COUNT.

## Disappearing messages shipped, and §28 has them as a future enhancement

That is the largest divergence in this document. They are **on by default at 48
hours**, per conversation, and either participant can turn them off — the
setting is `conversations.disappear_after_seconds`, fixed at 172800 or NULL
rather than a menu of durations.

The timer is **snapshotted at send**: `messages.expires_at` is stamped when the
row is written, so changing the setting never reaches back and re-dates what has
already been said. Turning it off does not resurrect anything.

Cleanup is two halves, and only one of them has to run:

- **The read filter is correctness.** A message whose `expires_at` has passed is
  invisible in every query in the repository, instantly, whether or not anything
  has swept.
- **`purge_expired` is storage.** It hard-deletes the rows and destroys the
  Cloudinary photos so a disappeared conversation stops costing anything. It runs
  opportunistically — on every send and every thread open, scoped to that one
  conversation — inside a SAVEPOINT, with the Cloudinary destroys after the
  commit boundary so a slow provider cannot stall a send. Passing
  `conversation_id=None` does a whole-table pass, which is the hook a future cron
  calls. **Threads with an OPEN report are spared**, because otherwise reporting
  abuse would destroy the evidence of it (§23).

## Jinja renders no part of a conversation

`app/templates/messages.html` and `app/templates/partials/thread.html` hold
furniture only: the boxes, the tabs, the sheets, the states that carry no data.
Every row, every bubble, every preview and the composer's disabled reason is
drawn by `app/static/js/cartflow-messages.js` from
`GET /api/messages/threads/{username}`.

The split is not a style preference. A bubble has to be drawable from a socket
frame, so it must have a JavaScript renderer; drawing it in Jinja *as well* would
be two renderers for one row, and the day they disagree is the day the same
message reads differently depending on whether you scrolled to it or watched it
land. So there is exactly one renderer for anything with a message in it.

Its consequence for time: **the server ships every timestamp twice**, raw ISO and
pre-rendered (`time_label`, `exact_time`), so the browser never formats its own.
The two exceptions are the ones the server genuinely cannot answer — the day
heading over a bubble group (a day boundary is the viewer's midnight and the app
stores no per-user timezone, which is why `exact_time` says UTC out loud) and the
countdown on a message about to disappear.

## §22 and §25, as enforced

A blocked sender and a handle that never existed get **the same 404**, in both
directions, and `/messages/@someone` renders byte-identically for both — asserted
by comparing the two responses with the handle normalised out. A "you have been
blocked" message, or a Message button that quietly disappeared, would tell them
what the service layer spends its length refusing to say. A non-participant
asking for someone else's thread gets 404, not 403 (§25): 403 confirms the thread
exists.

## Where a conversation starts

- The profile's **Message** button → `/messages/@{handle}`, rendered for every
  signed-in viewer including a blocked one (see above).
- The profile share sheet's **Send in a message** → `?share_user={handle}`, a
  `shared_profile` card.
- The home feed's share → `?share={product-slug}`, taken from the post's first
  tagged product, a `shared_product` card.
- The product page's **Send in a message** → the same, with its own slug.

In all four the query string only *carries* the thing. **Nothing is sent by a
GET** — a GET that sent a message would fire again on a refresh, on the back
button, and on any prefetch, and the user would never know, because what fired is
a page load. `tests/test_inboxes.py` counts the `conversations` and `messages`
tables either side of four such GETs and requires both to still be zero. The send
is a POST from the compose picker, whose candidates come from the follow graph
minus anyone blocked either way.

Neither value is validated by the page, for the same reason as §22: /messages
answering whether a slug or a handle exists is /messages answering a question the
service layer refuses. An unknown one fails at the POST, in the API's wording.

## Still not built, and why

- **§28's list stands, minus disappearing messages:** no group chats, voice or
  video messages, reactions, polls, pinned messages, message search, calls.
- **Shared posts and shared events** (§12, §14). Home-feed posts are a Jinja
  literal with no permalink and events have no table, so either card would link
  nowhere. A product shares fine because `/product/{slug}` is a real URL.
- **No cron.** `purge_expired` is correct without one — the read filter does the
  work — but until something calls it with `conversation_id=None`, storage is
  only reclaimed in conversations somebody still visits.

## Two things that will bite in production

- **The socket registry is a per-process dict** (`app/services/realtime.py`), so
  a message sent on one worker cannot reach a socket held by another.
  `docs/engineering/31-deployment-and-infrastructure.md:234` recommends multiple
  workers; that and this feature are in conflict until the fan-out goes through a
  shared broker. Single worker is correct for now, and the failure mode if it is
  ignored is quiet: messages still send, they just stop arriving live for some
  pairs of users. Reconnect-and-refetch masks it, which is what makes it quiet.
- **`0010_disappearing_messages` needs applying to Supabase.** Tests get the
  whole schema free from `create_all`, so a green suite says nothing about
  whether production has the column.

**Tests:** four files. `tests/test_messaging.py` walks §6's state machine row by
row, plus unread counts, read receipts, `?before=` paging, the 30-per-minute send
ceiling and §25. `tests/test_blocking.py` asserts the no-oracle property in both
directions and on the profile page, and covers reports — validation, note-folding
on a retry, the 429, and an SMTP failure leaving a visible unmailed row.
`tests/test_disappearing_messages.py` covers the snapshot-at-send rule, the read
filter, and the open-report reprieve. `tests/test_inboxes.py` asserts that
`/messages` ships **no** conversation server-side — no `data-msg`, no `data-row`,
no `data-tick`, and no `href="/messages/@` — because a server-rendered bubble
would be the second renderer this design exists to avoid. The bubble *CSS* does
ship with that page, and must: the page that draws bubbles needs the styles for
one. What must not ship is an instance.

---

# End of Document