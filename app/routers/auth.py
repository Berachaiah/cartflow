"""
Authentication and signup endpoints.

Per PRD Chapter 3, Section 4 (Student Sign-Up Flow, Steps 1-2) and
Section 9 (Email Verification, Steps 3-6).
"""

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.exceptions import ConflictError, RateLimitedError, UnauthorizedError
from app.database.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SimpleMessageResponse,
    UsernameAvailableResponse,
    VerifyEmailRequest,
    VerifyOtpRequest,
)
from app.schemas.user import (
    BusinessUpgradeRequest,
    BusinessUpgradeResponse,
    GraduationRequest,
    GraduationResponse,
    SignUpRequest,
    SignUpResponse,
    StudentSignUpRequest,
    StudentSignUpResponse,
    UserOut,
    validate_username_value,
)
from app.services import firebase_auth, google_oauth
from app.services.account import set_graduation, upgrade_to_business
from app.services.auth import find_user_for_google, signup as signup_service, signup_student
from app.services.email_verification import (
    request_verification_resend,
    verify_email_token,
)
from app.services.password_reset import request_password_reset
from app.services.password_reset import reset_password as reset_password_service
from app.services.password_reset import verify_reset_credential
from app.services.session import create_session
from app.services.session import login as login_service
from app.services.session import logout as logout_service

settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Short-lived cookie carrying the OAuth state nonce from /google/login to the
# callback, binding the flow to this browser. 15 min matches the signed state's
# own max age (google_oauth._STATE_MAX_AGE_SECONDS).
_OAUTH_STATE_COOKIE = "cartflow_oauth_state"
_OAUTH_STATE_COOKIE_MAX_AGE = 15 * 60


def _set_session_cookie(response: Response, raw_token: str, *, remember: bool) -> None:
    """Attach the session cookie. Shared by password login and the Google
    callback so both honour the same HttpOnly/secure/samesite policy."""
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        # No max_age => a session cookie the browser drops on close. That is
        # what "Remember me" unchecked has to mean; the server-side Session
        # row still expires on its own schedule either way.
        max_age=settings.SESSION_MAX_AGE_SECONDS if remember else None,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def _signup_success_message(result) -> str:
    return "Account created. Please check your email to verify your address."


@router.post("/signup", response_model=SignUpResponse, status_code=201)
async def signup_endpoint(
    payload: SignUpRequest,
    db: AsyncSession = Depends(get_db),
):
    """Unified multi-persona signup (student / individual / business).

    A `google_token` on the payload is the passwordless finish-signup path: the
    token is verified here, the identity unpacked, and the account created with
    password_hash=NULL, google_sub set, email pre-verified. The unified schema
    already enforces exactly-one-of(password, google_token)."""
    google_sub = None
    if payload.google_token is not None:
        identity = google_oauth.verify_finish_signup_token(payload.google_token)
        google_sub = identity["sub"]
        # Trust the token's verified email over anything posted alongside it —
        # the email is Google-verified and the account is created from it.
        payload.email = identity["email"]

    result = await signup_service(db, payload, google_sub=google_sub)

    if result.outcome == "pending_organization_review":
        return SignUpResponse(
            outcome=result.outcome,
            message=(
                "Your organization isn't listed yet, so we've submitted it for "
                "review. We'll email you to finish setting up your account once "
                "it's approved — no need to sign up again."
            ),
            organization_request_id=result.organization_request_id,
        )

    return SignUpResponse(
        outcome=result.outcome,
        message=_signup_success_message(result),
        user=UserOut.model_validate(result.user),
        organization_created=result.organization_created,
    )


@router.post("/signup/student", response_model=StudentSignUpResponse, status_code=201)
async def signup_student_endpoint(
    payload: StudentSignUpRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await signup_student(db, payload)

    if result.outcome == "pending_organization_review":
        return StudentSignUpResponse(
            outcome=result.outcome,
            message=(
                "Your organization isn't listed yet, so we've submitted it for "
                "review. We'll email you to finish setting up your account once "
                "it's approved — no need to sign up again."
            ),
            organization_request_id=result.organization_request_id,
        )

    return StudentSignUpResponse(
        outcome=result.outcome,
        message="Account created. Please check your email to verify your address.",
        user=UserOut.model_validate(result.user),
        organization_created=result.organization_created,
    )


@router.post("/verify-email", response_model=SimpleMessageResponse)
async def verify_email_endpoint(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    await verify_email_token(db, payload.token)
    return SimpleMessageResponse(message="Your email has been verified.")


@router.post("/resend-verification", response_model=SimpleMessageResponse)
async def resend_verification_endpoint(
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a fresh verification link.

    Always the same 200, whether or not the address is registered — this
    must not double as an account-existence oracle. The cost of that is
    that genuine failures are silent too, which is exactly why the lookup
    has to be right: signup stores `email` lowercased, so matching on the
    raw input would quietly miss anyone who typed a capital letter.
    """
    generic = SimpleMessageResponse(
        message="If that email is registered, a verification link has been sent."
    )

    user = await UserRepository(db).get_by_email(payload.email.lower())
    if user is None:
        return generic

    try:
        await request_verification_resend(db, user)
    except (ConflictError, RateLimitedError):
        # ConflictError = already verified. RateLimitedError = a link went
        # out moments ago. Both would confirm the address is registered, so
        # both collapse into the generic reply. Suppressing the send is the
        # control; announcing the suppression is what leaks.
        return generic

    return generic


@router.post("/login")
async def login_endpoint(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user, raw_token = await login_service(
        db,
        identifier=payload.identifier,
        password=payload.password,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    _set_session_cookie(response, raw_token, remember=payload.remember)

    return {"user": UserOut.model_validate(user)}


# --- Firebase Google sign-in ------------------------------------------


class FirebaseSignInRequest(BaseModel):
    """Body of POST /api/auth/firebase.

    A length floor is not security (the token is verified properly below) — it
    rejects an obviously empty field before any key fetching happens, so a
    busted client costs no network round trip to Google.
    """

    id_token: str = Field(min_length=64, max_length=8192)


@router.post("/firebase")
async def firebase_signin_endpoint(
    payload: FirebaseSignInRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Turn a Firebase ID token into a CartFlow session.

    This is the popup counterpart of the `/google/callback` redirect below, and
    it deliberately shares that flow's decisions:

      * a returning Google user (matched by google_sub, then email) gets a
        session and is sent to /discover;
      * a brand-new Google user is sent to `/signup?google=<token>` to choose a
        persona, because Google proves an email address but says nothing about
        whether someone is a student, an individual or a brand.

    The response body carries `next` rather than a server-side redirect: the
    call is made by `fetch` from the page, which cannot follow a 303 into a
    Set-Cookie any more reliably than it can read a cross-origin one. The client
    assigns `location` once it has the answer.
    """
    if not settings.firebase_enabled:
        raise ConflictError("Google sign-in is not enabled.")

    identity = firebase_auth.verify_id_token(payload.id_token)

    # Only a Google-verified address may create or match an account: an
    # unverified one would let somebody claim an email they do not own.
    if not identity["email_verified"]:
        raise UnauthorizedError("Google has not verified that email address yet.")

    user = await find_user_for_google(db, sub=identity["sub"], email=identity["email"])

    if user is None:
        token = google_oauth.issue_finish_signup_token(identity)
        return JSONResponse({"next": f"/signup?google={token}"})

    raw_token = await create_session(
        db,
        user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    # Remembered, for the same reason the redirect flow remembers: choosing
    # Google means Google is the durable login.
    response = JSONResponse({"next": "/discover"})
    _set_session_cookie(response, raw_token, remember=True)
    return response


# --- Google OAuth -----------------------------------------------------


@router.get("/google/login")
async def google_login_endpoint(
    intent: str = Query(default="login", pattern="^(login|signup)$"),
):
    """Kick off Google sign-in. Redirects the browser to Google's consent
    screen. `intent` (login|signup) is round-tripped in a signed state param so
    the callback knows which page the user came from. 404 when Google isn't
    configured — the button is hidden in that case anyway.

    A random nonce is embedded in the signed state AND dropped in a short-lived
    HttpOnly cookie; the callback requires the two to match, binding the flow to
    this browser (login-CSRF defence)."""
    if not settings.google_oauth_enabled:
        raise ConflictError("Google sign-in is not enabled.")
    authorize_url, nonce = google_oauth.build_authorize_url(intent)
    redirect = RedirectResponse(authorize_url, status_code=302)
    redirect.set_cookie(
        key=_OAUTH_STATE_COOKIE,
        value=nonce,
        max_age=_OAUTH_STATE_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    return redirect


@router.get("/google/callback")
async def google_callback_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Google redirects here after consent.

    - User cancelled / Google error → back to /login with a flag.
    - Existing user (matched by google_sub, then email) → create a session,
      set the cookie, land on /discover.
    - New user → mint a short-lived finish-signup token and send them to
      /signup?google=<token> to pick a username + role (+ org).
    """
    if not settings.google_oauth_enabled:
        raise ConflictError("Google sign-in is not enabled.")

    # The nonce this browser was given at /google/login. Consumed once here.
    state_nonce = request.cookies.get(_OAUTH_STATE_COOKIE)

    if error or not code or not state:
        resp = RedirectResponse("/login?google_error=1", status_code=302)
        resp.delete_cookie(_OAUTH_STATE_COOKIE)
        return resp

    # Verify state (signature + intent + browser-bound nonce) before spending a
    # token exchange on it.
    google_oauth.verify_state(state, state_nonce)
    identity = await google_oauth.exchange_and_identify(code)

    user = await find_user_for_google(db, sub=identity["sub"], email=identity["email"])

    if user is not None:
        raw_token = await create_session(
            db,
            user,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        # Returning Google users are "remembered" — they chose Google as their
        # durable login, so a persistent cookie matches intent.
        redirect = RedirectResponse("/discover", status_code=302)
        _set_session_cookie(redirect, raw_token, remember=True)
        redirect.delete_cookie(_OAUTH_STATE_COOKIE)
        return redirect

    # New user → finish signup (username + role + optional org).
    token = google_oauth.issue_finish_signup_token(identity)
    resp = RedirectResponse(f"/signup?google={token}", status_code=302)
    resp.delete_cookie(_OAUTH_STATE_COOKIE)
    return resp


# --- Capability transitions (Start selling / Graduation) --------------


@router.post("/business/upgrade", response_model=BusinessUpgradeResponse)
async def business_upgrade_endpoint(
    payload: BusinessUpgradeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The "Start selling" CTA. Creates a Business org the user owns and flips
    is_seller — WITHOUT changing account_type (a student stays a student)."""
    result = await upgrade_to_business(
        db,
        current_user,
        business_name=payload.business_name,
        state=payload.state,
    )
    return BusinessUpgradeResponse(
        message="Your business is set up. You can now sell on CartFlow.",
        user=UserOut.model_validate(result.user),
        organization_id=result.organization.id,
    )


@router.post("/graduation", response_model=GraduationResponse)
async def graduation_endpoint(
    payload: GraduationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Self-toggle graduation. When marking graduated AND the user owns a
    business, the response asks the client to prompt for a pickup-address
    review. No badge is set anywhere."""
    result = await set_graduation(db, current_user, graduated=payload.graduated)
    if result.graduated:
        message = (
            "You're marked as graduated."
            + (
                " Update your business pickup address if it has changed."
                if result.needs_pickup_update
                else ""
            )
        )
    else:
        message = "Graduation status cleared."
    return GraduationResponse(
        message=message,
        graduated_at=result.user.graduated_at,
        needs_pickup_update=result.needs_pickup_update,
    )


@router.post("/logout", response_model=SimpleMessageResponse)
async def logout_endpoint(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if raw_token:
        await logout_service(db, raw_token)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return SimpleMessageResponse(message="You have been logged out.")


@router.get("/me", response_model=UserOut)
async def get_current_user_endpoint(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


# --- Username availability -------------------------------------------


@router.get("/check-username", response_model=UsernameAvailableResponse)
async def check_username_endpoint(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    """Live availability check for the signup form.

    Advisory only. The authoritative guards are the unique index on
    users.username_normalized and the ConflictError in signup_student —
    two users racing on the same name a millisecond apart will both see
    "available" here, and the loser gets a clean 409 at submit time.

    Format is validated before touching the database so a malformed
    candidate gets the specific reason it's invalid rather than a
    misleading "available".
    """
    candidate = username.strip()

    try:
        validate_username_value(candidate)
    except ValueError as exc:
        return UsernameAvailableResponse(
            username=candidate, available=False, reason=str(exc)
        )

    taken = await UserRepository(db).username_exists(candidate.lower())
    return UsernameAvailableResponse(
        username=candidate,
        available=not taken,
        reason="This username is already taken." if taken else None,
    )


# --- Password reset ---------------------------------------------------


@router.post("/forgot-password", response_model=SimpleMessageResponse)
async def forgot_password_endpoint(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Email a reset link AND a 6-digit code.

    Always 200 with the same body, whether or not the account exists —
    this endpoint must not double as an account-existence oracle. The one
    exception is the per-account cooldown (429), which only fires for a
    requester who already triggered a send seconds earlier.
    """
    message = await request_password_reset(db, payload.identifier)
    return SimpleMessageResponse(message=message)


@router.post("/verify-reset-otp", response_model=SimpleMessageResponse)
async def verify_reset_otp_endpoint(
    payload: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    """Check a reset credential without consuming it.

    For the OTP path this costs one attempt against the cap when wrong and
    leaves the token usable when right, so the user isn't asked to type the
    code twice. For the link path it lets the reset page detect a stale
    link before the user picks a new password.
    """
    await verify_reset_credential(
        db,
        token=payload.token,
        identifier=payload.identifier,
        otp_code=payload.otp_code,
    )
    return SimpleMessageResponse(message="Verified. Choose a new password.")


@router.post("/reset-password", response_model=SimpleMessageResponse)
async def reset_password_endpoint(
    payload: ResetPasswordRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Set a new password via the link token or the OTP.

    Every session for the account is destroyed server-side, so this request's
    own cookie is stale on return — clear it and make the user log in with
    the new password. That is also the confirmation that the reset took.
    """
    await reset_password_service(
        db,
        new_password=payload.new_password,
        token=payload.token,
        identifier=payload.identifier,
        otp_code=payload.otp_code,
    )

    response.delete_cookie(settings.SESSION_COOKIE_NAME)

    return SimpleMessageResponse(
        message="Your password has been changed. Log in with your new password."
    )
