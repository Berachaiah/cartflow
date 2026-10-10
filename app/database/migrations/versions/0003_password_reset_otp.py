"""verification_tokens: add otp_hash + otp_attempts for password reset

Revision ID: 0003_password_reset_otp
Revises: 0002_organizations
Create Date: 2026-08-08

Password reset gives the user two ways to prove mailbox ownership — an
emailed link and an emailed 6-digit code — and both are carried by a
single verification_tokens row so they share one expiry and one used_at.
Redeeming either path therefore burns the other.

Columns added:
  otp_hash      SHA-256 of the 6-digit code. NULL for email_verification
                rows, which have no code path. Indexed for lookup but
                NOT unique: two users can legitimately draw the same six
                digits, and a unique index would reject the second insert.
  otp_attempts  Wrong-guess counter. A 6-digit code is only 10^6 wide, so
                without a cap it falls to brute force in minutes. Five
                misses burn the row (app.models.verification_token
                .MAX_OTP_ATTEMPTS).

server_default="0" on otp_attempts, not just a Python-side default: the
NOT NULL would otherwise fail against any row already in the table, and
raw SQL inserts that bypass the ORM would too.

Runs on Postgres (Supabase); the test suite builds its schema with
create_all on SQLite rather than running migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_password_reset_otp"
down_revision: Union[str, None] = "0002_organizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "verification_tokens",
        sa.Column("otp_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "verification_tokens",
        sa.Column(
            "otp_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_verification_tokens_otp_hash",
        "verification_tokens",
        ["otp_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_verification_tokens_otp_hash", table_name="verification_tokens")
    op.drop_column("verification_tokens", "otp_attempts")
    op.drop_column("verification_tokens", "otp_hash")
