"""
SMTP email sending via the Hacom mailbox (notifications@cartflow.appotg.com),
replacing the earlier Resend-based sender. Same public interface
(`send_email(to, subject, html) -> str`) so callers don't need to change.

Hacom's cPanel mail server enforces a 1,500/day sending limit on this
mailbox — worth keeping in mind if other transactional email (receipts,
notifications) gets added later; may be worth a separate mailbox/quota
for those so one flood doesn't starve the other.
"""

import uuid
from email.message import EmailMessage

import aiosmtplib

from app.core.config import get_settings

settings = get_settings()


async def send_email(*, to: str, subject: str, html: str) -> str:
    """Sends an email via the Hacom SMTP mailbox. Returns a locally
    generated message id (SMTP itself doesn't hand one back the way
    Resend's API did) — used only for logging/correlation.
    """
    message_id = str(uuid.uuid4())

    message = EmailMessage()
    message["From"] = settings.SMTP_USERNAME
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = f"<{message_id}@cartflow.appotg.com>"
    message.set_content("This email requires an HTML-capable email client.")
    message.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        message,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
        use_tls=settings.SMTP_USE_SSL,
    )

    return message_id
