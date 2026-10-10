"""users.full_name — separate the real name from the public display name

Revision ID: 0008_user_full_name
Revises: 0007_media
Create Date: 2026-08-16

Signup has always asked for a full name and then thrown the field away: the
service copied `payload.full_name` straight into `display_name` (four call sites
in app/services/auth.py) and stored nothing else. That conflated three different
ideas into two columns:

  username      the handle — unique, and the only unique one
  display_name  what you want to be called in public — not unique
  full_name     your real name — private

The distinction earns its keep in an app that takes money. A public profile
should show a handle and a chosen name; a delivery label, a receipt and a payout
account need the name on someone's ID. Keeping one column for both meant a
student who set their display name to "ada 💫" had no real name on file, and one
who wanted a nickname had to publish their legal name to get an order delivered.

**The backfill is exact, not a guess.** Every existing value in `display_name`
came from the signup `full_name` field, so copying it back is a restoration:

    UPDATE users SET full_name = display_name WHERE full_name IS NULL

Nullable, therefore, rather than NOT NULL with a default: after the backfill
every current row has a value, but "nobody has told us this yet" stays
representable for accounts created another way (a Google signup that only
supplied a given name, say). The application treats NULL as "ask for it at
checkout", which is honest; a NOT NULL column would have forced a placeholder
that reads like real data.

No index. `full_name` is never a lookup key — searching people goes through
`username_normalized` and `display_name`, and using a real name as a search key
across the whole platform is exactly the privacy behaviour we don't want.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_user_full_name"
down_revision: Union[str, None] = "0007_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=150), nullable=True))

    # Restore what signup discarded. Guarded on IS NULL so a re-run (or a
    # partially applied deploy) can't overwrite a name someone has since edited.
    op.execute(
        """
        UPDATE users
           SET full_name = display_name
         WHERE full_name IS NULL
        """
    )


def downgrade() -> None:
    # display_name still holds the same value for every row this migration
    # touched, so dropping the column loses nothing that wasn't already there.
    op.drop_column("users", "full_name")
