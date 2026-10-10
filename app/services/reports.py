"""
Reports — §23. Store the report, then email a human about it.

**The row comes first, the email second, and the email is allowed to fail.** A
report is a record; the mail is a notification about that record. If SMTP is down
and we sent mail before writing, the report would be lost precisely when someone
was trying hardest to be heard. So the order is fixed: insert, flush, send, and
stamp `emailed_at` only on success. A NULL `emailed_at` on an OPEN report means
"nobody has been told yet", which is a query an admin can run — a swallowed
exception with nothing in the table is not.

Sending inside the request transaction follows `email_verification.py`: flush,
then send. The narrow window it leaves — mail delivered for a report whose
transaction later rolls back — is the same window that file already accepts, and
inverting it (commit, then send in a background task) would need an infrastructure
piece this app does not have yet.

**Who can be reported.** Resolved WITHOUT the viewer's block check, exactly like
`messaging_service.block_user` and for a sharper version of the same reason: the
UI's Block-and-report sequence blocks first, and after that the pair is mutually
invisible — resolving with `viewer_id` would 404 the report half of a flow the
user just started. Worse, it would hand a harasser a way to shut off reports about
themselves by blocking their victim first. The cost is that reporting can confirm
a handle exists even when it has blocked you; being able to report the person who
blocked you is worth more than closing that one bit.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email_templates import render_email
from app.core.exceptions import RateLimitedError, ValidationAppError
from app.core.timeutils import absolute_time, utc_now
from app.integrations.smtp_client import send_email
from app.models.report import (
    REPORT_REASON_LABELS,
    REPORT_REASONS,
    Report,
    ReportStatus,
)
from app.models.user import User
from app.services import follow as follow_service
from app.services import messaging as messaging_service

logger = logging.getLogger(__name__)

# Long enough for a paragraph of context, short enough that the field is not a
# place to paste a whole thread. The thread is linked from the email anyway.
MAX_NOTE_CHARS = 1000

# A ceiling, not a dedupe: identical reports are folded below, so this exists to
# stop one account filing a hundred *different* reports in an afternoon. Generous
# on purpose — a bad hour genuinely can produce several real reports.
REPORT_LIMIT = 10
REPORT_WINDOW_HOURS = 1


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    cleaned = note.strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_NOTE_CHARS:
        raise ValidationAppError(
            "That note is too long.",
            fields={"note": f"Keep it under {MAX_NOTE_CHARS} characters."},
        )
    return cleaned


async def _enforce_report_limit(db: AsyncSession, reporter: User) -> None:
    since = utc_now() - timedelta(hours=REPORT_WINDOW_HOURS)
    stmt = (
        select(func.count())
        .select_from(Report)
        .where(Report.reporter_id == reporter.id, Report.created_at >= since)
    )
    result = await db.execute(stmt)
    if int(result.scalar_one() or 0) >= REPORT_LIMIT:
        raise RateLimitedError(
            "You've sent a lot of reports just now. Give it an hour and try again."
        )


async def _existing_open_report(
    db: AsyncSession, *, reporter_id: uuid.UUID, reported_user_id: uuid.UUID, reason: str
) -> Report | None:
    """The same complaint, already filed and not yet reviewed.

    Keyed on the reason as well as the pair, so a double-tap folds into one row
    while a genuinely different complaint about the same person still gets its
    own. Only OPEN rows fold: once a moderator has reviewed something, a fresh
    report about it is new information.
    """
    stmt = (
        select(Report)
        .where(
            Report.reporter_id == reporter_id,
            Report.reported_user_id == reported_user_id,
            Report.reason == reason,
            Report.status == ReportStatus.OPEN,
        )
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def submit_report(
    db: AsyncSession,
    *,
    reporter: User,
    username: str,
    reason: str,
    note: str | None = None,
    conversation_public_id: uuid.UUID | None = None,
) -> Report:
    """File a report about `username`. Returns the row, new or folded.

    `conversation_public_id` is optional context. When present it is checked
    through `messaging_service.require_participant`, so a report cannot be used
    to attach a stranger's thread id to a moderation record — a 404 for a
    conversation the reporter is not in, same as everywhere else.
    """
    if reason not in REPORT_REASONS:
        raise ValidationAppError(
            "Choose a reason for the report.",
            fields={"reason": "Pick one of the listed reasons."},
        )

    note = _clean_note(note)

    # See the module docstring: no viewer_id, on purpose.
    target = await follow_service.resolve_public_user(db, username=username)
    if target.id == reporter.id:
        raise ValidationAppError("You can't report yourself.")

    conversation_id: uuid.UUID | None = None
    if conversation_public_id is not None:
        conversation, _ = await messaging_service.require_participant(
            db, viewer=reporter, public_id=conversation_public_id
        )
        conversation_id = conversation.id

    existing = await _existing_open_report(
        db,
        reporter_id=reporter.id,
        reported_user_id=target.id,
        reason=reason,
    )
    if existing is not None:
        # Folded, and no second email: the moderator already has this one in
        # their inbox. A note added on the retry is still worth keeping, so it
        # lands on the row an admin will actually open.
        if note and not existing.note:
            existing.note = note
            await db.flush()
        return existing

    await _enforce_report_limit(db, reporter)

    report = Report(
        reporter_id=reporter.id,
        reported_user_id=target.id,
        conversation_id=conversation_id,
        reason=reason,
        note=note,
        status=ReportStatus.OPEN,
    )
    db.add(report)
    await db.flush()

    await _notify_admins(db, report=report, reporter=reporter, reported=target)
    return report


async def _notify_admins(
    db: AsyncSession, *, report: Report, reporter: User, reported: User
) -> None:
    """Best-effort admin email. Never raises — the report is already saved.

    A failure here is logged and left visible as `emailed_at IS NULL`. Letting
    the exception through would 500 a request whose real work succeeded, and
    would tell the reporter their report failed when it did not.
    """
    settings = get_settings()
    try:
        html = render_email(
            "report_received.html",
            reason_label=REPORT_REASON_LABELS.get(report.reason, report.reason),
            note=report.note,
            reporter_name=reporter.display_name,
            reporter_username=reporter.username,
            reported_name=reported.display_name,
            reported_username=reported.username,
            reported_email=reported.email,
            filed_at=absolute_time(report.created_at),
            report_id=str(report.public_id),
            has_thread=report.conversation_id is not None,
        )
        await send_email(
            to=settings.reports_email,
            subject=f"Report: {reported.username} — {report.reason}",
            html=html,
        )
    except Exception:  # noqa: BLE001 - deliberately broad, see docstring
        logger.exception(
            "Report %s saved but the admin email failed", report.public_id
        )
        return

    report.emailed_at = utc_now()
    await db.flush()
