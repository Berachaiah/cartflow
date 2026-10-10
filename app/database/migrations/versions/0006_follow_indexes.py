"""follow graph: index user_follows.following_id

Revision ID: 0006_follow_indexes
Revises: 0005_login_lockout
Create Date: 2026-08-15

`user_follows` has existed since the baseline migration but was never read by
any code. Profiles (`/@username`) are the first surface to use it, which turns
one direction of the graph into a hot path.

The table's primary key is the composite (follower_id, following_id). That
index serves follower_id-leading lookups — "who does X follow" — but a B-tree
on (a, b) cannot answer a query filtered on b alone. Every followers-direction
read does exactly that:

    WHERE following_id = :user      -- the follower COUNT on every profile
                                    -- render, and the Followers list

so without this index each one degrades to a full scan of the follow graph.

`uq_user_follows_pair` is left alone: it duplicates the primary key (same
columns, same order) and dropping it is an unrelated cleanup.

Runs on Postgres (Supabase). The test suite builds its schema with
`Base.metadata.create_all` rather than running migrations, so the index is also
declared on the model (`index=True` on UserFollow.following_id) — both are
needed, and they must stay in step.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0006_follow_indexes"
down_revision: Union[str, None] = "0005_login_lockout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_user_follows_following_id", "user_follows", ["following_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_user_follows_following_id", table_name="user_follows")
