"""stories

Revision ID: 0019_stories
Revises: 0018_admin_flag
Create Date: 2026-11-25

The rail above the feed. It shipped as decoration — shop avatars with a gradient
ring, a viewer showing a product photo — because there was nowhere to put a
story. `stories`, `story_likes` and `story_views` are that place, so a slide has
an author, a lifetime, and a record of who saw and liked it.

`expires_at` is nullable and NULL means "never expires": the seeded campus
stories are demo content that a walkthrough cannot lose overnight, while every
story created through the API sets now + 24h.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_stories"
down_revision: Union[str, None] = "0018_admin_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("image_url", sa.String(500), nullable=False),
        sa.Column("caption", sa.String(300), nullable=True),
        sa.Column("tagged_product_slug", sa.String(120), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repost_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repost_of_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repost_of_id"], ["stories.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_stories_author_id", "stories", ["author_id"])
    op.create_index("ix_stories_public_id", "stories", ["public_id"], unique=True)
    op.create_index("ix_stories_repost_of_id", "stories", ["repost_of_id"])
    op.create_index("ix_stories_expires_created", "stories", ["expires_at", "created_at"])

    op.create_table(
        "story_likes",
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("story_id", "user_id"),
        sa.UniqueConstraint("story_id", "user_id", name="uq_story_likes_story_user"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_story_likes_user_id", "story_likes", ["user_id"])

    op.create_table(
        "story_views",
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("story_id", "user_id"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_story_views_user_id", "story_views", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_story_views_user_id", table_name="story_views")
    op.drop_table("story_views")
    op.drop_index("ix_story_likes_user_id", table_name="story_likes")
    op.drop_table("story_likes")
    op.drop_index("ix_stories_expires_created", table_name="stories")
    op.drop_index("ix_stories_repost_of_id", table_name="stories")
    op.drop_index("ix_stories_public_id", table_name="stories")
    op.drop_index("ix_stories_author_id", table_name="stories")
    op.drop_table("stories")
