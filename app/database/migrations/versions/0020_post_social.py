"""post comments and reposts

Revision ID: 0020_post_social
Revises: 0019_stories
Create Date: 2026-11-25

The feed card has had a comment box and a repeat button since it was a Jinja
literal, and both were honest theatre: `toggleComments` unhid a list that was
empty, `repost()` showed a toast. `post_comments` and `post_reposts` make them
real, and `posts.repost_count` mirrors the second one the way `like_count`
already mirrors `post_likes`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_post_social"
down_revision: Union[str, None] = "0019_stories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("repost_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "post_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_post_comments_post_id", "post_comments", ["post_id"])
    op.create_index("ix_post_comments_post_created", "post_comments", ["post_id", "created_at"])

    op.create_table(
        "post_reposts",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("post_id", "user_id"),
        sa.UniqueConstraint("post_id", "user_id", name="uq_post_reposts_post_user"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_post_reposts_user_id", "post_reposts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_post_reposts_user_id", table_name="post_reposts")
    op.drop_table("post_reposts")
    op.drop_index("ix_post_comments_post_created", table_name="post_comments")
    op.drop_index("ix_post_comments_post_id", table_name="post_comments")
    op.drop_table("post_comments")
    op.drop_column("posts", "repost_count")
