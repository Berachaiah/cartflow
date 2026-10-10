"""
Thin wrapper around the Resend SDK.

Keeps the rest of the app decoupled from the specific email provider —
per PRD Chapter 12 sec 15 ("payment providers are accessed through an
abstraction layer"), the same principle applies to email.
"""

import resend

from app.core.config import get_settings

settings = get_settings()
resend.api_key = settings.RESEND_API_KEY


def send_email(*, to: str, subject: str, html: str) -> str:
    """Sends an email via Resend. Returns the provider's message id.

    Raises whatever exception the Resend SDK raises on failure — callers
    (the service layer) decide how to handle/log that, per Chapter 12's
    layering (integrations are dumb, services own business rules).
    """
    params: resend.Emails.SendParams = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "reply_to": settings.EMAIL_REPLY_TO or settings.EMAIL_FROM,
        "subject": subject,
        "html": html,
    }
    result = resend.Emails.send(params)
    return result["id"]
