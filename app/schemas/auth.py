"""Auth-flow request/response schemas (verification, login, password reset)."""

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# Kept in one place so the schema, the generator in core.security, and the
# UI's input maxlength can't drift apart.
OTP_LENGTH = 6


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class SimpleMessageResponse(BaseModel):
    message: str


# --- Password reset ---------------------------------------------------


class ForgotPasswordRequest(BaseModel):
    """Accepts a username OR an email, exactly like login.

    Not an EmailStr: forcing an email here would mean a user who signed up
    and remembers only their username has no way through the flow.
    """

    identifier: str = Field(min_length=1, max_length=255)

    @field_validator("identifier")
    @classmethod
    def strip_identifier(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Enter your username or email address")
        return cleaned


class VerifyOtpRequest(BaseModel):
    """Check a reset credential without consuming it.

    Accepts either path, because both screens need a pre-flight check:
    the OTP screen validates a typed code before advancing, and the reset
    screen validates an emailed link on arrival so a stale link is caught
    before the user picks and confirms a new password.
    """

    token: str | None = Field(default=None, min_length=10)
    identifier: str | None = Field(default=None, min_length=1, max_length=255)
    otp_code: str | None = Field(default=None, min_length=OTP_LENGTH, max_length=OTP_LENGTH)

    @model_validator(mode="after")
    def exactly_one_path(self):
        has_token = self.token is not None
        has_otp = self.identifier is not None and self.otp_code is not None

        if has_token and has_otp:
            raise ValueError("Send either a reset token or a code, not both")
        if not has_token and not has_otp:
            raise ValueError("A reset token, or your username/email plus the code, is required")

        if self.otp_code is not None:
            # Users paste codes with stray spaces from the email; strip
            # before validating so a harmless paste isn't rejected.
            cleaned = self.otp_code.strip().replace(" ", "")
            if not cleaned.isdigit() or len(cleaned) != OTP_LENGTH:
                raise ValueError(f"Enter the {OTP_LENGTH}-digit code from your email")
            self.otp_code = cleaned

        return self


class ResetPasswordRequest(BaseModel):
    """Consume EITHER a link token OR an identifier+OTP pair.

    The two paths are mutually exclusive on purpose: accepting both at once
    would leave "which one wins?" ambiguous, and an attacker could pair a
    valid token with a guessed OTP to probe the code space for free.
    """

    token: str | None = Field(default=None, min_length=10)
    identifier: str | None = Field(default=None, min_length=1, max_length=255)
    otp_code: str | None = Field(default=None, min_length=OTP_LENGTH, max_length=OTP_LENGTH)

    new_password: str = Field(min_length=8, max_length=255)
    confirm_password: str = Field(min_length=8, max_length=255)

    @model_validator(mode="after")
    def validate_one_path_and_match(self):
        has_token = self.token is not None
        has_otp = self.identifier is not None and self.otp_code is not None

        if has_token and has_otp:
            raise ValueError("Send either a reset token or a code, not both")
        if not has_token and not has_otp:
            raise ValueError("A reset token, or your username/email plus the code, is required")

        # Checked server-side as well as in the browser: the client-side
        # check is a convenience, and this endpoint is reachable directly.
        if self.new_password != self.confirm_password:
            raise ValueError("Those passwords don't match")

        if self.otp_code is not None:
            cleaned = self.otp_code.strip().replace(" ", "")
            if not cleaned.isdigit() or len(cleaned) != OTP_LENGTH:
                raise ValueError(f"Enter the {OTP_LENGTH}-digit code from your email")
            self.otp_code = cleaned

        return self


class UsernameAvailableResponse(BaseModel):
    """Live feedback for the signup form's username field.

    Only ever reports availability for a *well-formed* candidate, and never
    echoes back which account holds a taken name.
    """

    username: str
    available: bool
    reason: str | None = None


class LoginRequest(BaseModel):
    """Login takes one `identifier` that is either a username or an email.

    `email` stays as a deprecated alias so the existing V1 contract (and its
    tests) keep working. Validation is deliberately loose — `identifier` is
    NOT an EmailStr, because a username is equally valid here. Deciding which
    one it is happens in the service, on the normalized value.
    """

    identifier: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    password: str = Field(min_length=1)
    remember: bool = Field(
        default=False,
        description=(
            "True keeps the session cookie across browser restarts; False "
            "issues a session-scoped cookie that dies when the browser closes."
        ),
    )

    @model_validator(mode="after")
    def normalize_identifier(self):
        # Model-level, not field-level: the case we must catch is "neither
        # field was sent at all", and Pydantic v2 skips validators for fields
        # that fall back to their default.
        if self.identifier is None and self.email is not None:
            self.identifier = self.email
        if self.identifier is None or not self.identifier.strip():
            raise ValueError("Either identifier or email is required")
        self.identifier = self.identifier.strip()
        return self
