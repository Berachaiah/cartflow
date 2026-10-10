"""
Standardized exceptions and error-response formatting.

Response envelope follows PRD Chapter 12, section 48 "API Response and
Error Standards" (the authoritative technical-architecture chapter):

    Success:
        {"data": {...}, "meta": {...}}

    Error:
        {
          "error": {
            "code": "VALIDATION_ERROR",
            "message": "Please correct the highlighted fields.",
            "fields": {"price": "Enter a valid price."},
            "correlation_id": "..."
          }
        }

NOTE: docs/22-backend-architecture.md and docs/23-api-architecture.md (the
looser summary docs) describe a slightly different envelope
(`{"success": false, "message": ..., "error_code": ...}`). This scaffold
follows Chapter 12 since it's the more detailed, more recently dated
source — flag it if you want the summary-doc format instead, since routers
and any frontend fetch() calls will need to agree on one shape.

Never expose stack traces, SQL statements, secrets, or provider
credentials in error responses (PRD Ch.12 sec 48 / sec 38).
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("cartflow")


class AppException(Exception):
    """Base class for all domain/application errors.

    Raise a subclass (or this directly) from service-layer code; routers
    should not need to construct JSONResponse error bodies by hand.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "APPLICATION_ERROR"
    message: str = "Something went wrong. Please try again."

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        fields: dict[str, str] | None = None,
    ):
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        self.status_code = status_code or self.status_code
        self.fields = fields
        super().__init__(self.message)


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    message = "The requested resource was not found."


class ValidationAppError(AppException):
    status_code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY)
    error_code = "VALIDATION_ERROR"
    message = "Please correct the highlighted fields."


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"
    message = "This action conflicts with the current state of the resource."


class UnauthorizedError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"
    message = "Authentication is required."


class ForbiddenError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class RateLimitedError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMITED"
    message = "Too many requests. Please try again shortly."


class ServiceUnavailableError(AppException):
    """A dependency this feature needs isn't configured or isn't answering.

    503, not 500: nothing is broken and there is no bug to chase — the install is
    simply missing an integration (e.g. the CLOUDINARY_* credentials that back
    photo uploads). Distinguishing the two matters for both the client, which can
    say "not available yet" instead of "something went wrong", and for whoever
    reads the logs.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"
    message = "This feature isn't available right now."


def _error_body(code: str, message: str, correlation_id: str | None, fields: dict | None = None) -> dict:
    body = {"error": {"code": code, "message": message, "correlation_id": correlation_id}}
    if fields:
        body["error"]["fields"] = fields
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """Attach standardized JSON exception handlers to the FastAPI app."""

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException):
        correlation_id = getattr(request.state, "correlation_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message, correlation_id, exc.fields),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        correlation_id = getattr(request.state, "correlation_id", None)
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            fields[loc or "_"] = err.get("msg", "Invalid value.")
        return JSONResponse(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY),
            content=_error_body(
                "VALIDATION_ERROR", "Please correct the highlighted fields.", correlation_id, fields
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        correlation_id = getattr(request.state, "correlation_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("HTTP_ERROR", str(exc.detail), correlation_id),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.exception(
            "unhandled_exception",
            extra={"correlation_id": correlation_id, "path": request.url.path},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "INTERNAL_ERROR", "Something went wrong. Please try again.", correlation_id
            ),
        )
