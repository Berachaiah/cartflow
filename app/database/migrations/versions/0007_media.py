"""media table + users.profile_image_media_id FK

Revision ID: 0007_media
Revises: 0006_follow_indexes
Create Date: 2026-08-16

`users.profile_image_media_id` has existed since the baseline as a bare nullable
UUID with no foreign key, because there was no table to point at (see the comment
this migration's companion change removes from app/models/user.py). Profile photo
uploads need one, so this creates it and completes the reference.

Two details worth noting:

* **Adding the FK is safe on the live database.** The column is nullable and no
  code has ever written to it, so every existing row holds NULL and there are no
  values for Postgres to validate against the new `media` table. This is an
  `ADD CONSTRAINT` with nothing to check, not a data migration.

* **`ON DELETE SET NULL`, not CASCADE.** Deleting an image must never delete the
  account that used it; the profile just falls back to the drawn monogram.
  Ownership runs the other way (`media.owner_user_id` → users, ON DELETE CASCADE)
  so a hard-deleted account leaves no orphan media rows. CartFlow's user deletion
  is soft (`deleted_at`), so that cascade only fires on a genuine hard delete.

The test suite builds its schema with `Base.metadata.create_all`, not migrations,
so this file and app/models/media.py must stay in step. SQLite (the dev preview
DB) cannot ALTER TABLE ADD CONSTRAINT — see the guard in `upgrade()`; the
constraint still applies in tests and on Postgres, where it matters.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_media"
down_revision: Union[str, None] = "0006_follow_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_NAME = "fk_users_profile_image_media_id"


def upgrade() -> None:
    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("public_id", sa.String(length=255), nullable=False),
        sa.Column("secure_url", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(length=10), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Every "my media" read filters on the owner; unique on public_id because it
    # identifies one asset at the provider and two rows would both try to delete
    # the same remote file.
    op.create_index("ix_media_owner_user_id", "media", ["owner_user_id"], unique=False)
    op.create_index("ix_media_public_id", "media", ["public_id"], unique=True)

    # SQLite has no ALTER TABLE ADD CONSTRAINT. Alembic can emulate it by
    # rebuilding the table under batch_alter_table, but rebuilding `users` on a
    # throwaway preview DB buys nothing — the dev preview is created by
    # create_all, which already declares the FK.
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            _FK_NAME,
            "users",
            "media",
            ["profile_image_media_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    # Drop the FK first: `media` cannot be dropped while users still references it.
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(_FK_NAME, "users", type_="foreignkey")

    op.drop_index("ix_media_public_id", table_name="media")
    op.drop_index("ix_media_owner_user_id", table_name="media")
    op.drop_table("media")
