"""organizations: taxonomy + fold universities in + move users FK

Revision ID: 0002_organizations
Revises: 0001_baseline
Create Date: 2026-08-07

The V1 pivot from University-centric to Organization-centric (spec items #1/#2).

This migration:
  1. Creates the 5 organization tables (groups, types, organizations,
     organization_requests, signup_requests).
  2. Seeds the group/type taxonomy with DETERMINISTIC literal UUIDs, so the
     fold-in below (and future migrations) can reference the "University" type
     id directly.
  3. Folds every `universities` row into `organizations`, PRESERVING THE
     PRIMARY KEY — so existing `users.university_id` values still resolve after
     the FK is repointed. Every University column carries over 1:1 (including
     `institution_type`, which has its own column on Organization).
  4. Moves the users FK: adds `users.organization_id`, backfills it from
     `university_id`, adds the FK to `organizations`, then drops the old
     column + FK.

`universities` is intentionally LEFT INTACT (not dropped) — one release of
rollback safety. A later migration drops it once prod is verified.

Runs on Postgres (Supabase). Uses plain ALTER ops, not batch mode: the only
real execution target is Postgres, and the test suite builds its schema with
create_all on SQLite rather than running migrations.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_organizations"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Deterministic taxonomy UUIDs ----------------------------------------
# Hard-coded so the fold-in step (and any later migration/seed) can reference
# a specific group/type by id without a lookup. Do NOT change these once
# shipped — rows in prod point at them.
GROUP_IDS = {
    "education": uuid.UUID("11111111-0000-4000-8000-000000000001"),
    "business": uuid.UUID("11111111-0000-4000-8000-000000000002"),
    "government": uuid.UUID("11111111-0000-4000-8000-000000000003"),
    "non-profit": uuid.UUID("11111111-0000-4000-8000-000000000004"),
    "other": uuid.UUID("11111111-0000-4000-8000-000000000005"),
}

# The Education → University type: every folded-in university gets this.
UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")

GROUP_SEED = [
    {"id": GROUP_IDS["education"], "name": "Education", "slug": "education", "sort_order": 1},
    {"id": GROUP_IDS["business"], "name": "Business", "slug": "business", "sort_order": 2},
    {"id": GROUP_IDS["government"], "name": "Government", "slug": "government", "sort_order": 3},
    {"id": GROUP_IDS["non-profit"], "name": "Non-Profit", "slug": "non-profit", "sort_order": 4},
    {"id": GROUP_IDS["other"], "name": "Other", "slug": "other", "sort_order": 5},
]

# (id, group, name, slug, sort_order)
TYPE_SEED = [
    (UNIVERSITY_TYPE_ID, "education", "University", "university", 1),
    (uuid.UUID("22222222-0000-4000-8000-000000000002"), "education", "Polytechnic", "polytechnic", 2),
    (uuid.UUID("22222222-0000-4000-8000-000000000003"), "education", "College", "college", 3),
    (uuid.UUID("22222222-0000-4000-8000-000000000004"), "education", "Monotechnic", "monotechnic", 4),
    (uuid.UUID("22222222-0000-4000-8000-000000000005"), "education", "Training Institute", "training-institute", 5),
    (uuid.UUID("22222222-0000-4000-8000-000000000011"), "business", "Startup", "startup", 1),
    (uuid.UUID("22222222-0000-4000-8000-000000000012"), "business", "SME", "sme", 2),
    (uuid.UUID("22222222-0000-4000-8000-000000000013"), "business", "Enterprise", "enterprise", 3),
    (uuid.UUID("22222222-0000-4000-8000-000000000021"), "government", "Ministry", "ministry", 1),
    (uuid.UUID("22222222-0000-4000-8000-000000000022"), "government", "Agency", "agency", 2),
    (uuid.UUID("22222222-0000-4000-8000-000000000031"), "non-profit", "NGO", "ngo", 1),
    (uuid.UUID("22222222-0000-4000-8000-000000000032"), "non-profit", "Foundation", "foundation", 2),
    (uuid.UUID("22222222-0000-4000-8000-000000000041"), "other", "Other", "other", 1),
]




def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Create the taxonomy tables                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "organization_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_organization_groups_name"),
    )
    op.create_index("ix_organization_groups_slug", "organization_groups", ["slug"], unique=True)

    op.create_table(
        "organization_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("organization_group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_group_id"], ["organization_groups.id"], name="fk_org_types_group_id"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_group_id", "slug", name="uq_org_type_group_slug"),
    )
    op.create_index("ix_organization_types_group_id", "organization_types", ["organization_group_id"])
    op.create_index("ix_organization_types_slug", "organization_types", ["slug"])

    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_type_id", sa.Uuid(), nullable=True),
        sa.Column("official_name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=50), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False, server_default="Nigeria"),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("institution_type", sa.String(length=50), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_type_id"], ["organization_types.id"], name="fk_organizations_type_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_index("ix_organizations_type_id", "organizations", ["organization_type_id"])

    op.create_table(
        "organization_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("requested_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False, server_default="Nigeria"),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("organization_type_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("resulting_organization_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_type_id"], ["organization_types.id"], name="fk_org_requests_type_id"
        ),
        sa.ForeignKeyConstraint(
            ["resulting_organization_id"], ["organizations.id"], name="fk_org_requests_result_org_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_requests_status", "organization_requests", ["status"])

    op.create_table(
        "signup_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=30), nullable=False),
        sa.Column("username_normalized", sa.String(length=30), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("organization_request_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("resulting_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_request_id"], ["organization_requests.id"], name="fk_signup_requests_org_request_id"
        ),
        sa.ForeignKeyConstraint(
            ["resulting_user_id"], ["users.id"], name="fk_signup_requests_result_user_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signup_requests_email", "signup_requests", ["email"])
    op.create_index("ix_signup_requests_username_normalized", "signup_requests", ["username_normalized"])
    op.create_index("ix_signup_requests_org_request_id", "signup_requests", ["organization_request_id"])
    op.create_index("ix_signup_requests_status", "signup_requests", ["status"])

    # ------------------------------------------------------------------ #
    # 2. Seed the taxonomy                                               #
    # ------------------------------------------------------------------ #
    groups_tbl = sa.table(
        "organization_groups",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(groups_tbl, GROUP_SEED)

    types_tbl = sa.table(
        "organization_types",
        sa.column("id", sa.Uuid()),
        sa.column("organization_group_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        types_tbl,
        [
            {
                "id": type_id,
                "organization_group_id": GROUP_IDS[group_key],
                "name": name,
                "slug": slug,
                "sort_order": sort_order,
            }
            for (type_id, group_key, name, slug, sort_order) in TYPE_SEED
        ],
    )

    # ------------------------------------------------------------------ #
    # 3. Fold universities -> organizations (preserving the PK)          #
    # ------------------------------------------------------------------ #
    # A single INSERT...SELECT: the DB copies each column natively, so no row
    # is ever materialized in Python (avoids driver-specific UUID/datetime
    # round-trip issues) and it runs identically on Postgres and SQLite.
    #   - id is copied verbatim  -> users.university_id keeps resolving.
    #   - organization_type_id is set to the seeded University type.
    #   - country is defaulted to Nigeria (existing data is all Nigerian).
    #   - institution_type / aliases / source_metadata carry over 1:1.
    op.execute(
        sa.text(
            "INSERT INTO organizations "
            "(id, created_at, updated_at, deleted_at, organization_type_id, "
            " official_name, short_name, slug, country, state, institution_type, "
            " aliases, source_metadata, status) "
            "SELECT id, created_at, updated_at, deleted_at, :type_id, "
            " official_name, short_name, slug, 'Nigeria', state, institution_type, "
            " aliases, source_metadata, status "
            "FROM universities"
        ).bindparams(sa.bindparam("type_id", value=UNIVERSITY_TYPE_ID, type_=sa.Uuid()))
    )

    # ------------------------------------------------------------------ #
    # 4. Move the users FK: university_id -> organization_id             #
    # ------------------------------------------------------------------ #
    op.add_column("users", sa.Column("organization_id", sa.Uuid(), nullable=True))
    # Fold-in preserved ids, so this is a straight copy that satisfies the FK.
    op.execute("UPDATE users SET organization_id = university_id")
    op.create_foreign_key(
        "fk_users_organization_id", "users", "organizations", ["organization_id"], ["id"]
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_university_id")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_university_id_fkey")
    op.drop_column("users", "university_id")


def downgrade() -> None:
    # Reverse of step 4: restore users.university_id from organization_id.
    op.add_column("users", sa.Column("university_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE users SET university_id = organization_id")
    op.create_foreign_key(
        "fk_users_university_id", "users", "universities", ["university_id"], ["id"]
    )
    op.drop_constraint("fk_users_organization_id", "users", type_="foreignkey")
    op.drop_column("users", "organization_id")

    # Drop the 5 tables in FK-dependency-safe order. `universities` was never
    # dropped, so nothing there to restore.
    op.drop_index("ix_signup_requests_status", table_name="signup_requests")
    op.drop_index("ix_signup_requests_org_request_id", table_name="signup_requests")
    op.drop_index("ix_signup_requests_username_normalized", table_name="signup_requests")
    op.drop_index("ix_signup_requests_email", table_name="signup_requests")
    op.drop_table("signup_requests")

    op.drop_index("ix_organization_requests_status", table_name="organization_requests")
    op.drop_table("organization_requests")

    op.drop_index("ix_organizations_type_id", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")

    op.drop_index("ix_organization_types_slug", table_name="organization_types")
    op.drop_index("ix_organization_types_group_id", table_name="organization_types")
    op.drop_table("organization_types")

    op.drop_index("ix_organization_groups_slug", table_name="organization_groups")
    op.drop_table("organization_groups")
