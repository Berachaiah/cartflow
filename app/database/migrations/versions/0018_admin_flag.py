"""admin flag

Revision ID: 0018_admin_flag
Revises: 0017_message_replies
Create Date: 2026-11-24

The operator console needs a capability flag on `users`. It is deliberately NOT
an `account_type`: that column means "how do you appear on CartFlow" (student,
business, organisation) and adding a fourth value there would make staff look
like a category of member to every public query. A boolean is auditable, is
per-user, and can be revoked without deleting an account.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_admin_flag"
down_revision: Union[str, None] = "0017_message_replies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Partial index: the console looks up "is this viewer staff" on every /admin
    # request, and there will only ever be a handful of TRUE rows.
    op.create_index(
        "ix_users_is_admin",
        "users",
        ["is_admin"],
        postgresql_where=sa.text("is_admin"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_is_admin", table_name="users")
    op.drop_column("users", "is_admin")
