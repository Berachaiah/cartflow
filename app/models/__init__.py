"""
Domain models. Import every model module here once it exists, so
Alembic's autogenerate (via app/database/migrations/env.py -> Base.metadata)
can discover all tables from a single import.

Full table/column reference: docs PRD Chapter 12, sections 10-20.
"""

from app.database.base import Base  # noqa: F401
from app.models.university import University  # noqa: F401
from app.models.organization import (  # noqa: F401
    Organization,
    OrganizationGroup,
    OrganizationStatus,
    OrganizationType,
)
# After `organization`: products.organization_id points at it.
from app.models.product import Product, ProductStatus  # noqa: F401
from app.models.organization_request import (  # noqa: F401
    OrganizationRequest,
    RequestStatus,
    SignupRequest,
    SignupRequestStatus,
)
# Imported before `user`: User.profile_image_media_id has a ForeignKey into
# `media`, so the table needs to be registered on Base.metadata alongside it.
from app.models.media import Media, MediaKind, MediaProvider  # noqa: F401
from app.models.user import AccountStatus, AccountType, User, UserFollow  # noqa: F401
from app.models.verification_token import TokenPurpose, VerificationToken  # noqa: F401
from app.models.session import Session  # noqa: F401
# Imported after BOTH `media` and `user`: Message has FKs into each
# (media_id, sender_id, shared_user_id).
from app.models.conversation import (  # noqa: F401
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    Message,
    MessageKind,
    MessageReaction,
    UserBlock,
)
# After `user`: posts.author_id, post_likes.user_id, post_comments.author_id
# and post_reposts.user_id point at it.
from app.models.post import (  # noqa: F401
    Post,
    PostComment,
    PostLike,
    PostRepost,
    PostStatus,
)
# After `user`: a story belongs to one account, and its likes/views name one.
from app.models.story import Story, StoryLike, StoryView  # noqa: F401
# After `user`: payments are per buyer, and checkout is the one place money moves.
from app.models.payment import Payment, PaymentStatus  # noqa: F401
# After `user`: a notification belongs to one account and may name an actor.
from app.models.notification import Notification, NotificationKind  # noqa: F401
# After `conversation`: reports.conversation_id points at it.
from app.models.report import (  # noqa: F401
    REPORT_REASON_LABELS,
    REPORT_REASONS,
    Report,
    ReportReason,
    ReportStatus,
)
# After `conversation`, `media` and `user`: pins and wallpapers point at all three.
from app.models.message_extras import ChatWallpaper, ConversationProduct, MessagePin  # noqa: F401
