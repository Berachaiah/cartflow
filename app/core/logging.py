"""
Structured logging configuration.

Per PRD Chapter 12, section 40 "Logging and Observability", every log
line should carry: timestamp, level, service, environment, request_id,
correlation_id, route, method, status_code, user_id (when safe), and
duration.

RequestContextMiddleware (see middleware.py) populates request_id /
correlation_id / route / method / status_code / duration into
`request.state`; this module wires that state into every log record
emitted during that request via a logging.Filter.
"""

import json
import logging
import sys
from contextvars import ContextVar

from app.core.config import get_settings

# Populated per-request by RequestContextMiddleware; read by JSONLogFormatter.
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)


def set_request_context(*, request_id: str | None = None, correlation_id: str | None = None, user_id: str | None = None) -> None:
    if request_id is not None:
        _request_id_ctx.set(request_id)
    if correlation_id is not None:
        _correlation_id_ctx.set(correlation_id)
    if user_id is not None:
        _user_id_ctx.set(user_id)


class RequestContextFilter(logging.Filter):
    """Injects request/correlation/user IDs from context vars into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        record.correlation_id = _correlation_id_ctx.get()
        record.user_id = _user_id_ctx.get()
        return True


class JSONLogFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str):
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": getattr(record, "request_id", None),
            "correlation_id": getattr(record, "correlation_id", None),
            "user_id": getattr(record, "user_id", None),
        }
        # Allow ad-hoc structured fields passed via logger.info(..., extra={...})
        for key in ("route", "method", "status_code", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONLogFormatter(service=settings.APP_NAME, environment=settings.APP_ENV))
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)

    # Quiet noisy third-party loggers unless we're debugging.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not settings.DEBUG else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
