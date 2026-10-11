"""Pinned messages and per-user chat wallpapers (migration 0011).

Pins are shared by both people in a 1:1 chat (either can pin or unpin), capped at
MAX_PINS per conversation. The cap is enforced in the service, not the schema,
so changing it later is a constant, not a migration.

Wallpapers are per user: each side picks their own. `conversation_id` NULL is that
user's default for every chat. A photo wallpaper is stored already cropped to the
chosen ratio (the client bakes the crop), and the screen fills with `cover`, so the
centre band is what every device shows: that is the "always visible" safe zone.
"""
import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MAX_PINS = 5
WALLPAPER_PRESETS = ("default", "dots", "grid", "lines", "sky", "mint", "peach", "lilac")
WALLPAPER_RATIOS = ("9:16", "3:4", "1:1", "16:9")


class MessagePin(Base, TimestampMixin):
    __tablename__ = "message_pins"
    __table_args__ = (Index("ix_message_pins_conversation", "conversation_id"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    pinned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ChatWallpaper(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chat_wallpapers"
    __table_args__ = (
        Index("ix_chat_wallpapers_user_chat", "user_id", "conversation_id", unique=True),
        Index(
            "ix_chat_wallpapers_user_default",
            "user_id",
            unique=True,
            postgresql_where=text("conversation_id IS NULL"),
            sqlite_where=text("conversation_id IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="preset")
    preset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )
    focus_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    focus_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    ratio: Mapped[str | None] = mapped_column(String(8), nullable=True)
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
