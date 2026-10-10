"""login lockout: failed_login_attempts + locked_until on users

Revision ID: 0005_login_lockout
Revises: 0004_multi_persona_auth
Create Date: 2026-08-15

Adds per-account brute-force / credential-stuffing protection to password login
(docs 05 sec 19-20, 03 sec 24), which until now was the one auth surface with no
throttle — the reset-OTP path was already capped, primary login was not.

Two columns on `users`, both driven by app/services/session.py's login():

  users.failed_login_attempts  NOT NULL, server_default 0. Consecutive wrong
                               passwords; reset to 0 on a successful login. The
                               NOT NULL would fail against existing rows without
                               the server_default, and raw inserts that bypass
                               the ORM need it too.
  users.locked_until           Nullable timestamp. Set to now + cooldown once the
                               attempt threshold is hit; login refuses (429) while
                               it's in the future, even with the correct password.
                               NULL = not locked.

Google-OAuth (passwordless) accounts never reach the password check, so the lock
only ever gates local-password login — a locked account can still sign in with
Google, which is intended (Google already proved identity).

Runs on Postgres (Supabase). Uses plain ALTER ops, not batch mode — the only
real execution target is Postgres, and the test suite builds its schema with
create_all on SQLite rather than running migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_login_lockout"
down_revision: Union[str, None] = "0004_multi_persona_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
