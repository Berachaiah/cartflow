from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.database.session import dispose_engine, engine
from app.routers import (
    auth,
    business,
    messages,
    organizations,
    pages,
    payments,
    posts,
    universities,
    users,
    ws,
)

settings = get_settings()
setup_logging()
logger = get_logger("cartflow.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"route": "-", "method": "-", "status_code": 0})
    yield
    await dispose_engine()
    logger.info("shutdown", extra={"route": "-", "method": "-", "status_code": 0})


app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG, lifespan=lifespan)

# --- Middleware (order matters: outermost added last runs first) --------
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.APP_SECRET_KEY,
    session_cookie=settings.SESSION_COOKIE_NAME,
    max_age=settings.SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=settings.is_production,
)
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

register_exception_handlers(app)

# --- Static assets: /static/css, /static/js, /static/images --------------
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# --- PWA: the two files that must live at the site root -------------------
#
# A service worker only controls pages under its own URL path, so `/sw.js` has
# to be served from the root: the same file under /static/sw.js would control
# /static/ and nothing else, and the app would never work offline. The manifest
# is placed at the root for the same reason — its relative `start_url`, `scope`
# and icon paths resolve from where the browser fetched it.
#
# `Cache-Control: no-cache` on the worker, and never a long max-age: the browser
# re-fetches the script on every navigation and only replaces the worker when
# the bytes change, so a cached copy would pin an old deploy indefinitely.
@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(
        _STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    return FileResponse(
        _STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )

# --- Health checks (PRD Ch.12 sec 40) ------------------------------------
@app.get("/health/live", include_in_schema=False)
async def health_live():
    """Liveness: confirms the process is running."""
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    """Readiness: confirms required dependencies (DB) are reachable."""
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception:
        logger.exception("readiness_check_failed")
        return {"status": "degraded", "database": "unreachable"}


# --- Page routes (server-rendered Jinja2 templates) -----------------------
app.include_router(pages.router)
app.include_router(organizations.router)
app.include_router(organizations.taxonomy_router)
app.include_router(universities.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(business.router)
app.include_router(messages.router)
app.include_router(posts.router)
# Flutterwave: the checkout call, its redirect back, and the signed webhook.
app.include_router(payments.router)
# The messaging socket. Registered like any other router — it declares
# @router.websocket, so there is nothing special to mount, and no middleware here
# touches it: SessionMiddleware only reads the cookie the handshake already
# carries, and the security headers apply to the HTTP upgrade response.
app.include_router(ws.router)

# Future: app.include_router(api_router, prefix="/api/v1")
