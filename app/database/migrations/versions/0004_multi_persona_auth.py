"""multi-persona auth: passwordless + is_seller + google_sub + graduation + org ownership

Revision ID: 0004_multi_persona_auth
Revises: 0003_password_reset_otp
Create Date: 2026-08-12

Opens signup beyond university students (individuals + local businesses) and
adds Google OAuth, a seller capability, graduation handling, and business
ownership of organizations. The identity model separates two axes that used to
be conflated:

  - account_type (persona: student / individual / business) — descriptive.
  - is_seller (capability) — owning a Business-group organization. A student
    who starts a business KEEPS account_type=student and gains is_seller=True.

Columns added / altered:

  users.password_hash  -> made NULLABLE. Google-OAuth accounts are passwordless
                          (identity proven via Google, never a local password).
  users.is_seller      NOT NULL, server_default false. The NOT NULL would fail
                        against existing rows without the server_default, and
                        raw inserts that bypass the ORM need it too.
  users.google_sub     Google account "sub". NULL for password accounts.
                        UNIQUE so one Google account maps to one CartFlow user;
                        indexed for the returning-user lookup (matched before
                        email). A unique index tolerates many NULLs on both
                        Postgres and SQLite.
  users.graduated_at   Nullable timestamp; set when a student self-marks as
                        graduated. No badge is derived from it.

  organizations.owner_user_id   Nullable FK -> users.id. Source of truth for
                                 the seller capability (curated education orgs
                                 leave it NULL). Indexed for "orgs I own".
  organizations.pickup_address  Nullable; where buyers collect orders.

Runs on Postgres (Supabase). Uses plain ALTER ops, not batch mode — the only
real execution target is Postgres, and the test suite builds its schema with
create_all on SQLite rather than running migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_multi_persona_auth"
down_revision: Union[str, None] = "0003_password_reset_otp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ------------------------------------------------------------ #
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        "users",
        sa.Column(
            "is_seller",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("google_sub", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("graduated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_google_sub", "users", ["google_sub"], unique=True
    )

    # --- organizations ---------------------------------------------------- #
    op.add_column(
        "organizations",
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("pickup_address", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_organizations_owner_user_id",
        "organizations",
        ["owner_user_id"],
    )
    op.create_foreign_key(
        "fk_organizations_owner_user_id",
        "organizations",
        "users",
        ["owner_user_id"],
        ["id"],
    )


def downgrade() -> None:
    # --- organizations ---------------------------------------------------- #
    op.drop_constraint(
        "fk_organizations_owner_user_id", "organizations", type_="foreignkey"
    )
    op.drop_index("ix_organizations_owner_user_id", table_name="organizations")
    op.drop_column("organizations", "pickup_address")
    op.drop_column("organizations", "owner_user_id")

    # --- users ------------------------------------------------------------ #
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "graduated_at")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "is_seller")
    # Re-tighten password_hash. Any passwordless (Google) accounts must be
    # reconciled before a real downgrade — flagged, not silently coerced.
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
