"""
Conversation repository — every messaging query in one place.

The service above this owns the rules (§6's one-message state machine, blocks,
rate ceilings); this file owns the SQL. Two constraints shape most of it:

**It must run identically on SQLite and Postgres.** The test suite and
`dev_preview.db` are SQLite, production is Supabase Postgres. That rules out
`DISTINCT ON` for "the newest message per conversation" (hence the denormalised
`conversations.last_message_*` columns) and `NULLS LAST` (hence `coalesce` in the
inbox sort, since SQLite only learned `NULLS LAST` in 3.30).

**Account visibility is passed in, not decided here.** `hidden_statuses` is a
parameter rather than an import of `follow_service.HIDDEN_PROFILE_STATUSES`,
because the block check lives inside `resolve_public_user()` — so a repository
that imported the follow service would close a cycle the moment that lands. The
policy stays in the service layer where the rest of it already is.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.timeutils import utc_now
from app.models.conversation import (
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    Message,
    UserBlock,
    pair_key,
)
from app.models.media import Media
from app.models.report import Report, ReportStatus
from app.models.user import User, UserFollow
from app.repositories.base import BaseRepository


def _live_message_clause(now: datetime):
    """The read-side of disappearing messages: a message is *live* unless it has
    an expiry that has already passed.

    NULL `expires_at` means "never disappears" and must read as live — which
    ``expires_at > now`` alone does NOT deliver, because in SQL a NULL compared
    to anything is NULL (falsy), so a bare ``>`` would hide every permanent
    message. Hence the explicit OR. Applied everywhere a message is counted or
    listed (thread, unread, badge) so an expired message is invisible the instant
    it expires, independent of whether the storage-reclaiming sweep has run yet.
    """
    return or_(Message.expires_at.is_(None), Message.expires_at > now)


def _not_blocked_clause(viewer_id: uuid.UUID, other_id):
    """"No block in either direction between these two" — §22 for the *list* side.

    `other_id` is a column from the enclosing query (the other participant's
    `user_id`), so this correlates rather than taking a set of ids as a parameter.

    The send path checks a block one row at a time (`is_blocked_between`), which
    covers writing but not reading: a blocked pair must have no conversation
    *anywhere*, and a thread that 404s when opened while still showing a preview,
    a presence dot and an unread badge in the inbox is a block that announces
    itself — precisely what §22 forbids. So every query that lists or counts
    threads carries this too.

    NOT EXISTS rather than `NOT IN (blocked_or_blocking_ids(...))`: the id set
    would be a second round trip whose size grows with however many people the
    viewer has blocked, while this uses `user_blocks`' composite primary key in one
    direction and its index on `blocked_id` in the other.
    """
    return ~(
        select(UserBlock.blocker_id)
        .where(
            or_(
                and_(
                    UserBlock.blocker_id == viewer_id,
                    UserBlock.blocked_id == other_id,
                ),
                and_(
                    UserBlock.blocker_id == other_id,
                    UserBlock.blocked_id == viewer_id,
                ),
            )
        )
        .exists()
    )


@dataclass
class InboxRow:
    """One row of the inbox, assembled by a single query.

    `me` is my own participant row, carried through because the template needs
    `archived_at` and the read position, and re-fetching it per row would turn
    one query into N.
    """

    conversation: Conversation
    other: User
    me: ConversationParticipant
    unread: int


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Conversation)

    # ------------------------------------------------------------------ lookup

    async def get_by_public_id(self, public_id: uuid.UUID) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.public_id == public_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_between(
        self, user_a_id: uuid.UUID, user_b_id: uuid.UUID
    ) -> Conversation | None:
        """The 1:1 conversation these two share, if there is one.

        One indexed lookup on `pair_key` — the same canonical key the UNIQUE
        constraint enforces, so "find it" and "there can only be one" are
        answered by the same column rather than by a join that agrees with it by
        convention.

        Returns None for `user_a_id == user_b_id`: a self-pair collapses to a key
        that would match a thread with itself. The service refuses self-messaging
        before it gets here; this is the second line of defence.
        """
        if user_a_id == user_b_id:
            return None

        stmt = select(Conversation).where(
            Conversation.pair_key == pair_key(user_a_id, user_b_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_participant(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationParticipant | None:
        """My side of a thread — and the membership check §25 turns on.

        A None here is what makes "somebody else's conversation" a 404 rather
        than a 403: the caller cannot distinguish it from a thread that never
        existed, which is the point.
        """
        stmt = select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def other_participant(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> ConversationParticipant | None:
        stmt = select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id != user_id,
        )
        result = await self.db.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def participant_user_ids(self, conversation_id: uuid.UUID) -> set[uuid.UUID]:
        """Everyone in this thread, including the caller — the audience for a frame
        about the conversation itself (a status flip, a settings change).

        Both sides rather than just "the other one", because the sender's own other
        tabs need the frame too: a thread accepted on a phone should stop showing
        Accept on the laptop. The caller drops itself when a frame is meant only
        for the far side.
        """
        stmt = select(ConversationParticipant.user_id).where(
            ConversationParticipant.conversation_id == conversation_id
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def other_user(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> User | None:
        """The person on the other side, loaded as a User.

        Separate from `other_participant` because the thread header needs the
        account (name, handle, avatar, presence) while accept/decline only need
        the participant row.
        """
        stmt = (
            select(User)
            .join(
                ConversationParticipant,
                ConversationParticipant.user_id == User.id,
            )
            .where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id != user_id,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------- inbox

    def _unread_subquery(self, participant, user_id: uuid.UUID, now: datetime):
        """COUNT of the other side's messages I have not read yet.

        Correlated against the outer `conversations` row and my participant
        alias, so the whole inbox is one query rather than one-plus-N. Soft
        deleted messages are excluded, and `last_read_at IS NULL` means "never
        opened", so every message counts.

        Expired messages do not count: a message that has disappeared cannot be
        unread, or a thread whose only new message vanished at 48h would keep a
        badge nobody can ever clear.
        """
        return (
            select(func.count(Message.id))
            .where(
                Message.conversation_id == Conversation.id,
                Message.sender_id != user_id,
                Message.deleted_at.is_(None),
                _live_message_clause(now),
                or_(
                    participant.last_read_at.is_(None),
                    Message.created_at > participant.last_read_at,
                ),
            )
            .correlate(Conversation, participant)
            .scalar_subquery()
        )

    async def list_inbox(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool = False,
        requests_only: bool = False,
        accepted_only: bool = False,
        query: str | None = None,
        hidden_statuses: Sequence[str] = (),
        limit: int = 50,
        offset: int = 0,
    ) -> list[InboxRow]:
        """My inbox, newest activity first.

        The three `*_only` flags are the tabs, and they are mutually exclusive by
        convention rather than by assertion — the service picks exactly one from
        `?filter=`, so an impossible combination would simply return nothing.

        `query` is §20's search: display name, handle, or the business name of an
        account that owns one. Matched with LIKE on lowercased columns rather
        than `ilike`, because SQLite's LIKE is only case-insensitive for ASCII
        and this has to behave the same on both dialects.
        """
        mine = aliased(ConversationParticipant)
        theirs = aliased(ConversationParticipant)
        now = utc_now()

        stmt = (
            select(
                Conversation,
                User,
                mine,
                self._unread_subquery(mine, user_id, now).label("unread"),
            )
            .join(
                mine,
                and_(
                    mine.conversation_id == Conversation.id,
                    mine.user_id == user_id,
                ),
            )
            .join(
                theirs,
                and_(
                    theirs.conversation_id == Conversation.id,
                    theirs.user_id != user_id,
                ),
            )
            .join(User, User.id == theirs.user_id)
            .where(mine.archived_at.is_(None))
            .where(User.deleted_at.is_(None))
            .where(_not_blocked_clause(user_id, theirs.user_id))
        )

        if hidden_statuses:
            stmt = stmt.where(User.account_status.notin_(tuple(hidden_statuses)))

        if requests_only:
            # A request is a pending conversation somebody else started. The
            # initiator's own pending thread is not a request *to* them, so it
            # stays in All and out of this tab.
            stmt = stmt.where(
                Conversation.status == ConversationStatus.PENDING,
                Conversation.initiator_id != user_id,
            )
        elif accepted_only:
            stmt = stmt.where(Conversation.status != ConversationStatus.PENDING)

        if unread_only:
            stmt = stmt.where(self._unread_subquery(mine, user_id, now) > 0)

        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.display_name).like(needle),
                    User.username_normalized.like(needle),
                )
            )

        # coalesce, not `.desc().nullslast()`: SQLite only supports NULLS LAST
        # from 3.30, and a conversation with no messages yet should sort by when
        # it was created rather than falling to the bottom.
        stmt = stmt.order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()
        ).limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        return [
            InboxRow(conversation=c, other=u, me=p, unread=int(n or 0))
            for c, u, p, n in result.all()
        ]

    async def unread_conversation_count(
        self, user_id: uuid.UUID, *, hidden_statuses: Sequence[str] = ()
    ) -> int:
        """How many threads have something new in them — the nav badge.

        Threads, not messages: "3" next to the icon should mean three people are
        waiting, which is the number a user can act on. Counting messages makes
        one chatty friend look like a backlog.

        Carries the same visibility filters as `list_inbox` — block, deletion,
        moderation status — because a badge is a promise that opening the inbox will
        show you something. Count a thread the list then filters out and the number
        can never be cleared: nothing to open, nothing to mark read, a permanent 1.
        """
        mine = aliased(ConversationParticipant)
        theirs = aliased(ConversationParticipant)
        now = utc_now()
        has_unread = (
            select(Message.id)
            .where(
                Message.conversation_id == mine.conversation_id,
                Message.sender_id != user_id,
                Message.deleted_at.is_(None),
                _live_message_clause(now),
                or_(
                    mine.last_read_at.is_(None),
                    Message.created_at > mine.last_read_at,
                ),
            )
            .exists()
        )
        # The other side is joined in only to reach the visibility checks — the
        # count itself is over `mine`. Exactly one row matches, because a
        # conversation is always a pair (see `pair_key`), so this cannot
        # double-count a thread.
        stmt = (
            select(func.count())
            .select_from(mine)
            .join(
                theirs,
                and_(
                    theirs.conversation_id == mine.conversation_id,
                    theirs.user_id != user_id,
                ),
            )
            .join(User, User.id == theirs.user_id)
            .where(
                mine.user_id == user_id,
                mine.archived_at.is_(None),
                has_unread,
                User.deleted_at.is_(None),
                _not_blocked_clause(user_id, theirs.user_id),
            )
        )
        if hidden_statuses:
            stmt = stmt.where(User.account_status.notin_(tuple(hidden_statuses)))
        result = await self.db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def pending_request_count(
        self, user_id: uuid.UUID, *, hidden_statuses: Sequence[str] = ()
    ) -> int:
        """The count on the Requests tab: pending threads somebody else started.

        Same visibility filters as the tab it labels, for the same reason as
        `unread_conversation_count`.
        """
        mine = aliased(ConversationParticipant)
        theirs = aliased(ConversationParticipant)
        stmt = (
            select(func.count())
            .select_from(mine)
            .join(Conversation, Conversation.id == mine.conversation_id)
            .join(
                theirs,
                and_(
                    theirs.conversation_id == mine.conversation_id,
                    theirs.user_id != user_id,
                ),
            )
            .join(User, User.id == theirs.user_id)
            .where(
                mine.user_id == user_id,
                mine.archived_at.is_(None),
                Conversation.status == ConversationStatus.PENDING,
                Conversation.initiator_id != user_id,
                User.deleted_at.is_(None),
                _not_blocked_clause(user_id, theirs.user_id),
            )
        )
        if hidden_statuses:
            stmt = stmt.where(User.account_status.notin_(tuple(hidden_statuses)))
        result = await self.db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def partner_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """Everyone this user shares a thread with — who to tell about presence.

        Ids only, no User rows: the caller intersects this with the set of
        currently-connected sockets and throws most of it away, so loading
        accounts would be work for nothing.

        Deliberately ignores `archived_at` and `status`. Someone who archived our
        thread still has it, and can un-archive it by receiving a message; a
        pending request still shows the sender's presence in the recipient's
        inbox. Filtering either one would make the dot go stale in exactly the
        threads a user is most likely to be looking at.

        A block, though, is filtered: presence is the one thing that leaks without
        anybody asking for it, so a blocked pair going online must not light each
        other's dot in a thread neither of them can open.
        """
        mine = aliased(ConversationParticipant)
        theirs = aliased(ConversationParticipant)
        stmt = (
            select(theirs.user_id)
            .join(mine, mine.conversation_id == theirs.conversation_id)
            .where(
                mine.user_id == user_id,
                theirs.user_id != user_id,
                _not_blocked_clause(user_id, theirs.user_id),
            )
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def usernames_for(self, user_ids: Iterable[uuid.UUID]) -> list[str]:
        """The handles behind a set of internal ids.

        The last step of the presence snapshot, and the only place the internal →
        public identifier translation happens for the socket layer. The registry
        keys sockets by `users.id` (which the client never sees) while the frames
        it sends carry `username` (which the client can match against a rendered
        row), so something has to bridge the two — a projection of one column,
        rather than loading whole accounts to read one field off each.
        """
        ids = tuple(user_ids)
        if not ids:
            return []
        stmt = select(User.username).where(
            User.id.in_(ids), User.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------ thread

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        *,
        before: datetime | None = None,
        limit: int = 30,
    ) -> list[Message]:
        """A page of the thread, oldest-first for rendering.

        Fetched newest-first so `LIMIT` takes the *recent* end and the composite
        index does the work, then reversed — a thread opens at the bottom.

        `before` is a strict `created_at` cursor. Two messages sharing an exact
        timestamp at a page boundary could in principle drop one; at
        microsecond resolution and human typing speed that does not happen, and
        the alternative (a compound cursor) is not worth the API surface.

        Expired messages are filtered out here, so a disappeared message is gone
        from the thread the instant it expires — not when the sweep next runs.
        """
        stmt = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
            _live_message_clause(utc_now()),
        )
        if before is not None:
            stmt = stmt.where(Message.created_at < before)
        stmt = stmt.order_by(Message.created_at.desc()).limit(limit)

        result = await self.db.execute(stmt)
        # .unique() is required: `media` and `shared_user` are lazy="joined", so
        # the result set arrives with joined-eager duplicates.
        newest_first = list(result.unique().scalars().all())
        newest_first.reverse()
        return newest_first

    async def get_message_by_public_id(self, public_id: uuid.UUID) -> Message | None:
        stmt = select(Message).where(
            Message.public_id == public_id, Message.deleted_at.is_(None)
        )
        result = await self.db.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def count_messages_since(
        self, sender_id: uuid.UUID, since: datetime
    ) -> int:
        """Messages this account has sent since `since` — the spam ceiling.

        Counts across every conversation, not per-thread: the abuse being
        prevented is one account spraying twenty people, which a per-thread
        limit would wave straight through. Soft-deleted rows still count, so
        deleting your own messages does not buy a fresh allowance.
        """
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.sender_id == sender_id, Message.created_at >= since)
        )
        result = await self.db.execute(stmt)
        return int(result.scalar_one() or 0)

    # ------------------------------------------------ disappearing / purge

    async def conversations_with_open_reports(self) -> set[uuid.UUID]:
        """Conversation ids that have at least one report still OPEN.

        The purge spares these: a disappeared message that is under active
        moderation has to survive until a moderator closes the report, or the
        act of reporting abuse would be the thing that destroys the evidence of
        it. Once the report flips to REVIEWED the thread rejoins the sweep and
        its expired rows are reclaimed on the next pass.
        """
        stmt = (
            select(Report.conversation_id)
            .where(
                Report.status == ReportStatus.OPEN,
                Report.conversation_id.is_not(None),
            )
            .distinct()
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def list_expired_messages(
        self,
        now: datetime,
        *,
        conversation_id: uuid.UUID | None = None,
    ) -> list[Message]:
        """Messages whose expiry has passed — the sweep's work list.

        Soft-deleted rows are included on purpose: a message that is both
        "deleted for me" and expired is invisible to everyone, so keeping the row
        (and its Cloudinary asset) buys nothing. `media` is eager-loaded on the
        model, so the caller can read each row's `public_id` to destroy the
        remote file without a second query — hence `.unique()`.

        Report-sparing is applied by the caller, not here: the common case is that
        nothing has expired, and checking that first (one indexed range scan) lets
        the sweep skip the open-reports lookup entirely on the vast majority of
        calls.
        """
        stmt = select(Message).where(
            Message.expires_at.is_not(None),
            Message.expires_at <= now,
        )
        if conversation_id is not None:
            stmt = stmt.where(Message.conversation_id == conversation_id)
        result = await self.db.execute(stmt)
        return list(result.unique().scalars().all())

    async def newest_visible_message(
        self, conversation_id: uuid.UUID, now: datetime
    ) -> Message | None:
        """The newest message that still shows in the thread — for recomputing the
        `last_message_*` mirror after a purge removes the row it used to point at.

        Same visibility rule as `list_messages`: not soft-deleted, not expired.
        Returns None when the purge emptied the conversation, and the caller then
        clears the mirror to NULL.
        """
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
                _live_message_clause(now),
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def delete_messages(self, message_ids: Iterable[uuid.UUID]) -> None:
        """Hard-delete message rows by id. `synchronize_session=False` because the
        purge does not reuse the loaded ORM objects after deleting them, and the
        default in-Python synchronisation would be wasted work on a bulk delete."""
        ids = tuple(message_ids)
        if not ids:
            return
        await self.db.execute(
            delete(Message)
            .where(Message.id.in_(ids))
            .execution_options(synchronize_session=False)
        )

    async def delete_media(self, media_ids: Iterable[uuid.UUID]) -> None:
        """Hard-delete media rows by id, after their remote assets are destroyed.

        Separate from `delete_messages` because `messages.media_id` is ON DELETE
        SET NULL, not CASCADE — deleting a message leaves its media row behind, so
        the disappearing sweep (which wants the storage back) has to remove it
        explicitly rather than relying on the FK.
        """
        ids = tuple(media_ids)
        if not ids:
            return
        await self.db.execute(
            delete(Media)
            .where(Media.id.in_(ids))
            .execution_options(synchronize_session=False)
        )

    # ------------------------------------------------------------------ blocks

    async def is_blocked_between(
        self, user_a_id: uuid.UUID, user_b_id: uuid.UUID
    ) -> bool:
        """True if either has blocked the other.

        Symmetric on purpose (§22): a block stops the conversation in both
        directions, so the blocker never has to worry about the reply, and the
        blocked user is never told which of the two directions applies.
        """
        stmt = (
            select(func.count())
            .select_from(UserBlock)
            .where(
                or_(
                    and_(
                        UserBlock.blocker_id == user_a_id,
                        UserBlock.blocked_id == user_b_id,
                    ),
                    and_(
                        UserBlock.blocker_id == user_b_id,
                        UserBlock.blocked_id == user_a_id,
                    ),
                )
            )
        )
        result = await self.db.execute(stmt)
        return int(result.scalar_one() or 0) > 0

    async def get_block(
        self, blocker_id: uuid.UUID, blocked_id: uuid.UUID
    ) -> UserBlock | None:
        stmt = select(UserBlock).where(
            UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def blocked_or_blocking_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """Everyone this user cannot see or be seen by, in one round trip.

        Used to filter the compose picker, where checking each candidate
        individually would be a query per row.
        """
        stmt = select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
        result = await self.db.execute(stmt)
        ids: set[uuid.UUID] = set()
        for blocker_id, blocked_id in result.all():
            ids.add(blocked_id if blocker_id == user_id else blocker_id)
        return ids

    # -------------------------------------------------------------- candidates

    async def list_candidates(
        self,
        user_id: uuid.UUID,
        *,
        query: str | None = None,
        hidden_statuses: Sequence[str] = (),
        limit: int = 20,
    ) -> list[User]:
        """Who the compose picker offers: people I follow, or who follow me.

        Scoped to the follow graph rather than every account on the platform.
        That is both the right default (these are the people you actually write
        to) and a deliberate refusal to open a user-enumeration endpoint for the
        sake of a convenience feature.
        """
        outbound = select(UserFollow.following_id).where(
            UserFollow.follower_id == user_id
        )
        inbound = select(UserFollow.follower_id).where(
            UserFollow.following_id == user_id
        )

        stmt = (
            select(User)
            # Two IN subqueries rather than a UNION: each rides its own index
            # (user_follows' PK leads on follower_id, and migration 0006 added
            # the following_id index for exactly this direction), and a compound
            # SELECT inside IN needs coercion gymnastics for no gain.
            .where(or_(User.id.in_(outbound), User.id.in_(inbound)))
            .where(User.id != user_id)
            .where(User.deleted_at.is_(None))
        )

        if hidden_statuses:
            stmt = stmt.where(User.account_status.notin_(tuple(hidden_statuses)))

        if query:
            needle = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.display_name).like(needle),
                    User.username_normalized.like(needle),
                )
            )

        stmt = stmt.order_by(User.display_name.asc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.unique().scalars().all())
