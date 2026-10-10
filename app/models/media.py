"""
Media — one row per uploaded file (PRD Chapter 12 sec 17).

This is the table `app/models/user.py` has been carrying an unbacked
`profile_image_media_id` for since the baseline schema. Avatars are the first
consumer, but the table is deliberately generic rather than an `avatars` table:
posts, products and event covers all need exactly this row, and a per-feature
image table would mean the same upload/delete/derive code written four times.

What is stored, and what isn't:

  * `public_id` is Cloudinary's identifier and the ONLY thing needed to build a
    URL at any size (app/integrations/cloudinary_client.build_url). It is the
    real key here.
  * `secure_url` is the canonical original as Cloudinary returned it. Kept for
    provenance and for a provider-agnostic fallback — do NOT render it directly
    for avatars; it is the full-size asset, not a sized derivative.
  * `width`/`height`/`format`/`bytes` are the provider's own report, useful for
    layout and for spotting a bad upload. Nullable: a provider may omit them.
  * No `alt` column yet. Avatars derive alt text from the account's name, and
    inventing an unused column now would only have to be migrated later.

`provider` exists so the row says where the bytes actually live. Cloudinary is
the only value today; a future move (or a second bucket for large video) has to
be able to tell rows apart, and back-filling a provider column onto live media
is the kind of migration that goes wrong.

Ownership is a hard FK with ON DELETE CASCADE: media belongs to the account that
uploaded it, and an account that is truly deleted should not leave orphan rows
pointing at files. Note that CartFlow's user deletion is SOFT (`deleted_at`), so
this only fires on a genuine hard delete.
"""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MediaProvider(str):
    """Not an Enum on purpose — the column is a plain String(20) so adding a
    provider needs no migration, matching how account_type/status are stored."""

    CLOUDINARY = "cloudinary"


class MediaKind(str):
    IMAGE = "image"
    VIDEO = "video"


class Media(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MediaProvider.CLOUDINARY
    )
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MediaKind.IMAGE
    )

    # Unique because it identifies one asset at the provider. A duplicate would
    # mean two rows whose lifecycles both delete the same remote file. Declared
    # as a unique INDEX (not a bare constraint) so create_all and migration
    # 0007_media produce the same object under the same name.
    public_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    secure_url: Mapped[str] = mapped_column(String(500), nullable=False)

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String(10), nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Media {self.public_id!r} ({self.kind})>"
