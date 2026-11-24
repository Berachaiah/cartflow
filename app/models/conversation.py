"""
Messaging models — conversations, participants, messages, and blocks.

Doc 10 §26 lists six tables (`conversations`, `conversation_participants`,
`messages`, `message_requests`, `message_attachments`, `message_reads`). This
module defines **four**, and the three folds are deliberate rather than
oversights:

  - **`message_requests` folds into `conversations.status`.** A message request
    *is* the conversation while it is pending; two tables would mean two places
    hold the answer to "who may write here", and they would drift. Note that
    DECLINED is a persisted status, not a deleted row: §6 says a deleted request
    still bars the sender from writing again, so the row has to survive the
    decline that caused it.
  - **`message_reads` folds into `ConversationParticipant.last_read_at`.** A row
    per message per reader buys nothing in a 1:1 chat: "have they read message N"
    is `N.created_at <= their last_read_at`, and my unread count is a COUNT of
    the other person's messages after mine. One column, no fan-out table.
  - **`message_attachments` folds into three nullable columns on `messages`.**
    One attachment per message in V1. Typed columns rather than a JSON payload,
    because a blob cannot be constrained, joined or indexed — and a shared
    profile needs a real FK so a deleted account does not leave a card pointing
    at nobody.

`ConversationParticipant` is kept even though every conversation in V1 has
exactly two rows. It is where per-side state lives (read position, archive), and
it makes group chats (§28) additive instead of a rewrite. The thread between two
people, however, is found by `conversations.pair_key` rather than by intersecting
that table: a participant-side intersection can *find* a thread but cannot stop a
second one being created for the same pair, which a UNIQUE key can. See
`pair_key()` below.

The `last_message_*` columns on `conversations` are denormalised mirrors of the
newest row in `messages`. They exist because the alternative for "last message
per conversation" is `DISTINCT ON` (Postgres-only) or loading every message to
render the inbox, and this app must behave identically on SQLite (the test suite
and dev_preview.db) and Postgres. They are written in exactly one place —
`messaging_service.send_message` — which is the only way a denormalised column
stays honest.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import (
    Base,
    PublicIdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# How long a message lives before it disappears, when a conversation has
# disappearing turned on. 48 hours, the value the user asked for. Stored on the
# conversation as a *seconds* count rather than a bool so that "let people pick
# 24h / 7 days / …" later is a value change, not a migration — V1 only ever
# writes this constant or NULL (off). Snapshot semantics: the value is read at
# send time and frozen onto the message's `expires_at`, so changing the timer
# (or turning it off) only affects messages sent *after* the change, exactly the
# way the disappearing-messages toggle behaves in the social apps it mimics.
DEFAULT_DISAPPEAR_SECONDS = 48 * 60 * 60  # 172800


def pair_key(user_a_id: uuid.UUID, user_b_id: uuid.UUID) -> str:
    """The canonical key for a 1:1 conversation between two accounts.

    Sorted, so `pair_key(a, b) == pair_key(b, a)` — which is what makes a plain
    UNIQUE constraint able to enforce "at most one thread between two people".
    Without it, two devices sending a first message simultaneously both find no
    conversation and both insert one, and the pair ends up with two threads and
    their messages split between them. No constraint over
    `conversation_participants` can express that rule, because two different
    conversation ids never collide there.
    """
    return ":".join(sorted((str(user_a_id), str(user_b_id))))


from sqlalchemy import Integer as _Integer  # noqa: E402


class ConversationStatus(str):
    """Not an Enum on purpose — the column is a plain String(20), so adding a
    status needs no migration. Same reasoning as MediaKind (app/models/media.py)
    and the String-backed account_type/account_status.

    PENDING   the initiator has sent their one message (§6); it sits in the
              recipient's Requests tab and the initiator cannot write again.
    ACCEPTED  both sides may write freely. Reached by Accept, or simply by the
              recipient replying — replying *is* accepting.
    DECLINED  the recipient deleted the request. The initiator is barred for
              good; the recipient may still change their mind and write, which
              flips it to ACCEPTED.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class MessageKind(str):
    """What the bubble renders. String(20), so this list can grow freely.

    SHARED_POST and SHARED_EVENT from §10 are absent on purpose: neither posts
    nor events have a table yet, so such a card could only link nowhere.
    """

    TEXT = "text"
    IMAGE = "image"
    SHARED_PRODUCT = "shared_product"
    SHARED_PROFILE = "shared_profile"
    OFFER = "offer"


class Conversation(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin):
    """One thread between two people.

    Addressed publicly by `public_id`, never by `id` — the internal PK is not a
    security boundary (see PublicIdMixin). In practice the UI addresses a thread
    by the other person's handle (`/messages/@ada`) and only the accept/decline/
    read endpoints need the id.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        # The inbox is "my conversations, newest activity first". The
        # participant-side index gets us the rows; this one keeps the sort from
        # being a filesort once an account has a few hundred threads.
        Index("ix_conversations_last_message_at", "last_message_at"),
        UniqueConstraint("pair_key", name="uq_conversations_pair_key"),
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConversationStatus.PENDING
    )

    # Canonical "these two people" key — see pair_key() above. Set once at
    # creation and never updated, so unlike the last_message_* mirrors below
    # there is nothing here that can drift out of step.
    #
    # NULLABLE, and that is the group-chat door (§28): both SQLite and Postgres
    # treat NULLs as distinct in a unique index, so any number of group
    # conversations can coexist with NULL here while 1:1 threads stay unique.
    # It is also why `find_between` refuses a self-pair — one row would satisfy
    # both sides of the key.
    pair_key: Mapped[str | None] = mapped_column(String(73), nullable=True)

    # Who sent the first message. This is the person §6's one-message rule binds,
    # and it stays put for the life of the conversation — it is not "who sent the
    # most recent message" (that is last_sender_id) and must never be updated.
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Disappearing-messages timer for THIS thread, in seconds. NULL means off —
    # messages sent while it is NULL never expire. New conversations default to
    # 48h (DEFAULT_DISAPPEAR_SECONDS); either participant can toggle it, and the
    # value is snapshotted onto each message's `expires_at` at send time, so a
    # change only governs messages sent afterwards. The read layer treats an
    # expired message as gone the instant `expires_at` passes; a separate sweep
    # reclaims the row and its photo (see messaging_service.purge_expired).
    disappear_after_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=DEFAULT_DISAPPEAR_SECONDS
    )

    # --- denormalised mirrors of the newest message (see module docstring) ---
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 160 chars because the inbox row shows one clamped line; storing the whole
    # body here would duplicate `messages.body` for no gain.
    last_message_preview: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Lets a row read "You: ..." without joining messages.
    last_sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # When the newest message expires, mirrored alongside the preview so the inbox
    # can blank a row whose last message has vanished without joining `messages`.
    # NULL when the last message does not disappear (timer off at send time). The
    # single writer is messaging_service._record_delivery, same as the rest.
    last_message_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Conversation {self.public_id} ({self.status})>"


class ConversationParticipant(Base, TimestampMixin):
    """One side of a conversation, and everything that is true of that side only.

    Composite PK (conversation_id, user_id) serves "who is in this thread".
    The extra (user_id, conversation_id) index serves the opposite and far more
    frequent question — "what is in my inbox" — which the PK cannot answer
    without a scan, exactly the asymmetry migration 0006 fixed for user_follows.
    """

    __tablename__ = "conversation_participants"
    __table_args__ = (
        Index(
            "ix_conversation_participants_user_conversation",
            "user_id",
            "conversation_id",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    # Does double duty, which is why there is no message_reads table: it is both
    # "how many of their messages are unread by me" and — read from the other
    # participant's row — "have they read mine yet" (§17). NULL means never
    # opened, so every message in the thread is unread.
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Per-side, so archiving hides the thread from my inbox and leaves theirs
    # untouched. Cleared when a new message arrives — an archived conversation
    # that someone writes into is back.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ConversationParticipant {self.user_id} in {self.conversation_id}>"


class Message(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """One message. Soft-deleted, so "delete for me" never rewrites history for
    the other side and a moderator can still read what was reported."""

    __tablename__ = "messages"
    __table_args__ = (
        # Thread paging: WHERE conversation_id = ? ORDER BY created_at DESC
        # LIMIT n, plus the ?before= cursor. Composite because filtering by
        # conversation alone would still sort every message in it.
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        # The disappearing sweep is WHERE expires_at <= now: a lone index on the
        # expiry column turns that from a full-table scan into a range scan, and
        # the NULLs (messages that never disappear) sort out of the way for free.
        Index("ix_messages_expires_at", "expires_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MessageKind.TEXT
    )

    # The text of a TEXT message, or the note typed alongside a share. Nullable
    # because a photo or a shared card with no caption is a complete message.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SET NULL rather than CASCADE: if the image is purged from Cloudinary the
    # message must survive as a record that something was sent, the same call
    # users.profile_image_media_id makes.
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )

    # Stored as the slug rather than a FK because the catalogue is still a
    # literal in the templates, not a `products` table. The slug is what
    # /product/{slug} routes on, so it keeps working when the table lands.
    shared_product_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Price offers (migration 0012): only kind == 'offer' rows use these.
    offer_price: Mapped[int | None] = mapped_column(_Integer, nullable=True)
    offer_listed: Mapped[int | None] = mapped_column(_Integer, nullable=True)
    offer_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # A real FK, so a shared profile card cannot outlive the account it points
    # at. SET NULL and the template falls back to "This account is no longer
    # available" instead of linking to a 404.
    shared_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # When this message disappears. Frozen at send time from the conversation's
    # timer (NULL if the timer was off then), so it is a per-message fact that a
    # later toggle cannot rewrite. Two consumers: the read layer hides any row
    # with expires_at <= now (instant, exact, independent of sweep timing), and
    # the sweep hard-deletes those rows to reclaim storage. Soft-delete
    # (`deleted_at`, "delete for me") and expiry are orthogonal — a message can
    # be soft-deleted before it expires, or expire having never been deleted.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Both eager: a thread renders every attachment it has, and a lazy load
    # outside the original greenlet raises MissingGreenlet under async
    # SQLAlchemy — the same reason User.profile_image is lazy="joined".
    # foreign_keys is pinned because `messages` has two FKs into `users`
    # (sender_id and shared_user_id) and SQLAlchemy cannot infer which this
    # relationship rides on.
    media: Mapped["Media | None"] = relationship(lazy="joined", foreign_keys=[media_id])
    shared_user: Mapped["User | None"] = relationship(
        lazy="joined", foreign_keys=[shared_user_id]
    )

    # --- quoted reply -------------------------------------------------
    # A reply POINTS AT the message it quotes rather than copying its text. The
    # copy would go stale the moment the original was edited or deleted-for-all,
    # and a quote of a deleted message should say it was deleted — which it can
    # only do if the link survives. ON DELETE SET NULL, so purging history leaves
    # the reply standing without a dangling target.
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # `remote_side` is required on a self-referential relationship: without it
    # SQLAlchemy cannot tell which end is the parent and raises at mapper config.
    # joined, for the same MissingGreenlet reason as `media` above.
    reply_to: Mapped["Message | None"] = relationship(
        lazy="joined",
        remote_side="Message.id",
        foreign_keys=[reply_to_id],
    )

    # selectin, not joined: a joined load here would multiply the thread query by
    # every reaction on every message. selectin is one extra query for the page.
    reactions: Mapped[list["MessageReaction"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="MessageReaction.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Message {self.public_id} ({self.kind})>"


class MessageReaction(Base, TimestampMixin):
    """One emoji, from one person, on one message (WhatsApp/iMessage shape).

    The PK is the whole row: reacting twice with the same emoji is the same fact,
    so a double-tap cannot inflate a count. Toggling is therefore a delete when
    the row exists and an insert when it does not — the client never sends
    "remove", it sends the emoji it wants and the server knows the current state.

    No `updated_at` meaning beyond the mixin: a reaction is not editable, it is
    added or removed.
    """

    __tablename__ = "message_reactions"
    __table_args__ = (
        # "what did I react to in this thread" — the only other query shape.
        Index("ix_message_reactions_user", "user_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Short by design: one grapheme cluster, not a sentence. Stored as the
    # literal character so the client needs no sprite sheet or lookup table.
    emoji: Mapped[str] = mapped_column(String(16), primary_key=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MessageReaction {self.emoji} on {self.message_id}>"


class UserBlock(Base, TimestampMixin):
    """Blocker → blocked. A pure association table, like UserFollow: unblocking
    is a hard delete of the row, so there is nothing to soft-delete.

    Both directions are checked on every send, because §22 is symmetric in
    effect — if either party has blocked the other, neither can write. The PK
    answers "who have I blocked"; the index on blocked_id answers "who has
    blocked me", which is the half a bare composite PK cannot serve.
    """

    __tablename__ = "user_blocks"

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UserBlock {self.blocker_id} -> {self.blocked_id}>"
