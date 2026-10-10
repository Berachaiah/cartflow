"""baseline: current schema (users, user_follows, universities, sessions, verification_tokens)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-07

This migration captures the schema as it already exists in Supabase (built
earlier via ad-hoc Base.metadata.create_all scripts). On the existing
database, run `alembic stamp 0001_baseline` so it is marked applied WITHOUT
re-running (the tables already exist). Fresh/dev/staging databases run
`alembic upgrade head`, which builds this and every later revision normally.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- universities -----------------------------------------------------
    op.create_table(
        "universities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("official_name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=50), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("institution_type", sa.String(length=50), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_universities_slug", "universities", ["slug"], unique=True)

    # --- users ------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("account_status", sa.String(length=30), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=30), nullable=False),
        sa.Column("username_normalized", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("bio", sa.String(length=500), nullable=True),
        sa.Column("profile_image_media_id", sa.Uuid(), nullable=True),
        sa.Column("university_id", sa.Uuid(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(username) >= 3", name="ck_users_username_min_length"),
        sa.CheckConstraint("length(username) <= 30", name="ck_users_username_max_length"),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"], name="fk_users_university_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_public_id", "users", ["public_id"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username_normalized", "users", ["username_normalized"], unique=True)

    # --- user_follows -----------------------------------------------------
    op.create_table(
        "user_follows",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("follower_id", sa.Uuid(), nullable=False),
        sa.Column("following_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], name="fk_user_follows_follower_id"),
        sa.ForeignKeyConstraint(["following_id"], ["users.id"], name="fk_user_follows_following_id"),
        sa.PrimaryKeyConstraint("follower_id", "following_id"),
        sa.UniqueConstraint("follower_id", "following_id", name="uq_user_follows_pair"),
    )

    # --- sessions ---------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_index("ix_sessions_session_token_hash", "sessions", ["session_token_hash"], unique=True)

    # --- verification_tokens ---------------------------------------------
    op.create_table(
        "verification_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_verification_tokens_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_tokens_user_id", "verification_tokens", ["user_id"], unique=False)
    op.create_index(
        "ix_verification_tokens_token_hash", "verification_tokens", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_table("verification_tokens")
    op.drop_table("sessions")
    op.drop_table("user_follows")
    op.drop_index("ix_users_username_normalized", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_public_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_universities_slug", table_name="universities")
    op.drop_table("universities")
