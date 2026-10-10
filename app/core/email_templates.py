"""
Jinja environment for transactional emails.

Separate from the Jinja2Templates instance the page routers use, because
the two have genuinely different requirements: page rendering needs a
Starlette `request` in context for url_for(), while an email is rendered
from a background/service context where no request exists. Sharing one
instance would mean either passing a fake request or losing autoescape.

Autoescaping is ON. Emails interpolate user-controlled values
(display_name, which is whatever the user typed at signup), so an
unescaped template would let a name containing markup break the layout
or smuggle a link into a message the recipient trusts.
"""

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings

# Resolved from this file's location, not the process's working directory.
# A relative "app/templates" only works when the server happens to be
# launched from the repo root — it breaks under systemd, a container with a
# different WORKDIR, or pytest invoked from a subdirectory, and the failure
# shows up as a TemplateNotFound at send time rather than at startup.
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        # Emails are whitespace-insensitive, but trimming keeps the source
        # readable without shipping a wall of blank lines to the client.
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Every URL in an email must be ABSOLUTE — there is no page it is relative
    # to. Page templates get that from url_for(); emails have no request, so
    # the base URL comes from configuration, which is also the only source the
    # services trust for the links they build (email_verification.py,
    # password_reset.py). Exposing it as a global rather than threading it
    # through every render_email() call keeps the two in step.
    #
    # NOT a secret: APP_BASE_URL is the public address of this install. Nothing
    # else from settings belongs in here (see the config module's own rule
    # about not leaking server secrets into templates).
    base_url = get_settings().APP_BASE_URL.rstrip("/")
    env.globals["APP_BASE_URL"] = base_url
    # The brand mark. Mail clients block remote images by default, so this is
    # never the only thing identifying the sender — the layout also prints the
    # wordmark as text. In local development APP_BASE_URL is 127.0.0.1, which
    # no real inbox can resolve; the alt text covers that until the app has a
    # public URL.
    env.globals["LOGO_URL"] = f"{base_url}/static/images/logo-icon.png"
    return env


def render_email(template_name: str, /, **context) -> str:
    """Render `app/templates/emails/<template_name>` to an HTML string."""
    return _env().get_template(f"emails/{template_name}").render(**context)
