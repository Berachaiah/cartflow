"""posts

Revision ID: 0014_posts
Revises: 0013_products
Create Date: 2026-11-23

The feed's first tables. Until now Home's posts were a Jinja literal, so a post
belonged to nobody: it could not appear on a profile and could not be liked by a
real account. `posts` + `post_likes` are what let Home, `/@handle` and Activity
describe the same post.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_posts"
down_revision: Union[str, None] = "0013_products"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("images", sa.JSON(), nullable=True),
        sa.Column("tagged_product_slugs", sa.JSON(), nullable=True),
        sa.Column("badge", sa.String(60), nullable=True),
        sa.Column("location", sa.String(120), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="published"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.CheckConstraint("like_count >= 0", name="ck_posts_like_count_non_negative"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_posts_author_id", "posts", ["author_id"])
    op.create_index("ix_posts_status", "posts", ["status"])
    op.create_index("ix_posts_status_created_at", "posts", ["status", "created_at"])

    op.create_table(
        "post_likes",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("post_id", "user_id"),
        sa.UniqueConstraint("post_id", "user_id", name="uq_post_likes_post_user"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_post_likes_user_id", "post_likes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_post_likes_user_id", table_name="post_likes")
    op.drop_table("post_likes")
    op.drop_index("ix_posts_status_created_at", table_name="posts")
    op.drop_index("ix_posts_status", table_name="posts")
    op.drop_index("ix_posts_author_id", table_name="posts")
    op.drop_table("posts")
