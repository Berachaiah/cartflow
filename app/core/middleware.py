"""
Cross-cutting middleware: request/correlation IDs, timing, structured
access logging, and baseline security headers.

CSRF protection (PRD Ch.12 sec 38) is intentionally NOT wired here yet —
it depends on the session/cookie-auth mechanism being built in the Auth
domain (double-submit cookie needs a place to mint/verify tokens against
the logged-in session). `core.security.generate_csrf_token` /
`constant_time_compare` are ready to use once that lands.
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.logging import get_logger, set_request_context

logger = get_logger("cartflow.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request_id and correlation_id to every request, times it,
    and emits one structured access-log line per request (PRD Ch.12 sec 40).
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID", request_id)

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        set_request_context(request_id=request_id, correlation_id=correlation_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "route": request.url.path,
                    "method": request.method,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                },
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "route": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security headers (PRD Ch.12 sec 38 Security Requirements).

    THE POLICY HAS TO MATCH THE TEMPLATES. The previous version allowlisted
    cdnjs.cloudflare.com, which base.html has never loaded anything from, while
    blocking all three origins it does load from and every inline <script> on the
    page. The failure mode is not a console warning: the Tailwind Play CDN is a
    script, so blocking it means no utility class in the entire app resolves, and
    the app renders as unstyled HTML on a dark background with the splash
    skeleton still up, because the script that dismisses it was inline and
    blocked too. That looked like a broken server rather than a broken header,
    which is exactly why it survived.

    Every source below is here because something on the page needs it — keep this
    list and the <head> of base.html in step.
    """

    # One entry per directive, so what is allowed is legible and greppable
    # against the templates rather than buried in a concatenated string.
    _CSP = {
        "default-src": ["'self'"],
        # https: for Cloudinary avatars and product photography; data: for the
        # inline SVG placeholders; blob: for the object URLs that show a chosen
        # photo BEFORE it is uploaded (profile.html, settings.html) — without it
        # the crop preview is a broken image at exactly the moment the user is
        # deciding whether to keep the picture.
        "img-src": ["'self'", "https:", "data:", "blob:"],
        # 'unsafe-inline' covers the page's own <style> blocks and the inline
        # style= attributes. No third-party stylesheet host remains: Tailwind is
        # a static file under 'self', and so is the vendored font CSS.
        "style-src": ["'self'", "'unsafe-inline'"],
        # No third-party script origin remains. cdn.jsdelivr.net served Twemoji
        # until that URL turned out to be a 404 (the upstream repo was archived)
        # and the dead <script> came out of base.html; cdn.tailwindcss.com went
        # when Tailwind was compiled to a static file.
        #
        # 'unsafe-inline' is a real weakening — with it, an injected <script>
        # runs. Every reason it HAD to be here is now gone: the Play CDN and its
        # inline `tailwind.config` are retired, so no third-party script can
        # inject scripts of its own and a nonce is no longer ruled out.
        #
        # It cannot go on its own, because five inline blocks remain — the theme
        # bootstrap that must resolve before first paint, the skeleton
        # dismissal, the emoji no-op, and the per-page scripts. Retiring it means
        # giving those a nonce, and with 'self' now the only other source that is
        # a change worth making rather than one that cannot work. Until then the
        # app's XSS defence rests on Jinja's autoescaping rather than on CSP,
        # which is why the escaping tests in tests/test_product_page.py matter.
        "script-src": [
            "'self'",
            "'unsafe-inline'",
        ],
        # 'self' serves the woff2 files from static/fonts; data: is kept for any
        # inlined face. fonts.gstatic.com is gone — scripts/vendor_fonts.py
        # brought the files local, so nothing here reaches Google any more.
        "font-src": ["'self'", "data:"],
        # Every fetch the app makes is same-origin (/api/...). Nothing here
        # should ever need widening; if it does, something is calling a third
        # party from the browser that should be called from the server.
        "connect-src": ["'self'"],
        # No <frame>/<object> anywhere, and X-Frame-Options only covers being
        # framed, not framing others.
        "frame-src": ["'none'"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
    }

    _CSP_HEADER = "; ".join(f"{key} {' '.join(sources)}" for key, sources in _CSP.items())

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        settings = get_settings()

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = self._CSP_HEADER
        if settings.is_production:
            # HSTS is deliberately production-only. On a dev box it would be
            # actively harmful: the browser remembers it per host, so one visit
            # to http://192.168.0.4:8000 would leave that address pinned to
            # https for two years, and phone testing over the LAN would stop
            # working with no obvious cause.
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

        return response
