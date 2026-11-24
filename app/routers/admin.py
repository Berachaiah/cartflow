"""The operator console: /admin.

WHY IT IS SERVER-RENDERED AND NOT A SPA. The console exists to answer "is this
thing healthy" in one request, from a phone, on a bad connection. Every chart on
it is drawn from numbers the server already had to read to render the tables, so
there is no second round trip and no window where the page says "loading" and
shows nothing.

WHY THE ANALYTICS ARE BUCKETED IN PYTHON. `date_trunc` is Postgres-only and the
test suite runs on SQLite. Pulling the six weeks of timestamps the console needs
and grouping them here keeps ONE query path that is correct on both, and the row
count is bounded by the window — this is not a table scan of every user.

WHY THE PASSWORD BANNER IS ENFORCED BY REDIRECT. A console that says "change the
default password" in a dismissible banner is a console with the default password.
Every GET under /admin except the account page sends a still-default operator to
the form, so the only way past it is to actually change it.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_optional
from app.core.security import hash_password, verify_password
from app.database.session import get_db
from app.models.conversation import Message
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.post import Post, PostLike, PostStatus
from app.models.product import Product, ProductStatus
from app.models.user import AccountStatus, User
# The SAME Jinja environment the public pages use, not a second one: base.html
# calls helpers (avatar, naira, time_ago) that pages.py registers as globals, and
# a fresh Jinja2Templates would render the shell with all of them undefined.
from app.routers.pages import templates

router = APIRouter(prefix="/admin", tags=["admin"])

# Postgres returns the enum MEMBERS, SQLite returns the raw strings, and the
# console renders both. One helper keeps the template from having to know which
# database it is talking to (`.value` on a str is an AttributeError, i.e. a 500
# on the only page that is supposed to tell you the app is healthy).
templates.env.globals["enum_label"] = lambda v: (
    "—" if v is None or v == "" else getattr(v, "value", v)
)

# The seeded first credential. Kept in one constant so the guard, the banner and
# the seed script cannot disagree about what "still the default" means.
DEFAULT_PASSWORD = "cartflow"
WINDOW_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _guard(user: User | None, request: Request) -> RedirectResponse | None:
    """Signed out → login (with a way back); signed in but not staff → 404.

    404 rather than 403 on purpose: a 403 confirms the route exists, which turns
    /admin into a probe target. A normal user typing it into the address bar gets
    the same answer as a typo'd URL.
    """
    if user is None:
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
    if not user.is_admin:
        return RedirectResponse("/", status_code=303)
    return None


def _must_change_password(user: User) -> bool:
    return verify_password(DEFAULT_PASSWORD, user.password_hash)


def _buckets(start: date, days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(days)]


def _daily(rows: list[datetime], since: date, days: int) -> list[int]:
    """Count timestamps per calendar day, in UTC.

    Uses the date the row was written, not the server's local day: two operators
    in two timezones must read the same chart.
    """
    seen = Counter()
    for ts in rows:
        if ts is None:
            continue
        day = ts.astimezone(timezone.utc).date() if ts.tzinfo else ts.date()
        seen[day] += 1
    return [seen.get(day, 0) for day in _buckets(since, days)]


async def _scalar(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar() or 0)


async def _dashboard_rows(db: AsyncSession) -> dict:
    now = _now()
    since_dt = now - timedelta(days=WINDOW_DAYS - 1)
    since_day = since_dt.date()

    # --- headline counts -------------------------------------------------
    users_total = await _scalar(
        db, select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    )
    users_7d = await _scalar(
        db,
        select(func.count())
        .select_from(User)
        .where(User.deleted_at.is_(None), User.created_at >= now - timedelta(days=7)),
    )
    posts_total = await _scalar(
        db,
        select(func.count())
        .select_from(Post)
        .where(Post.deleted_at.is_(None), Post.status == PostStatus.PUBLISHED.value),
    )
    products_total = await _scalar(
        db,
        select(func.count())
        .select_from(Product)
        .where(
            Product.deleted_at.is_(None), Product.status == ProductStatus.ACTIVE.value
        ),
    )
    revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.status == PaymentStatus.SUCCESSFUL.value
            )
        )
    ).scalar() or 0
    orders_paid = await _scalar(
        db,
        select(func.count())
        .select_from(Payment)
        .where(Payment.status == PaymentStatus.SUCCESSFUL.value),
    )

    # --- time series -----------------------------------------------------
    signup_rows = list(
        (
            await db.execute(
                select(User.created_at).where(
                    User.deleted_at.is_(None), User.created_at >= since_dt
                )
            )
        ).scalars()
    )
    paid_rows = list(
        (
            await db.execute(
                select(Payment.paid_at).where(
                    Payment.status == PaymentStatus.SUCCESSFUL.value,
                    Payment.paid_at.is_not(None),
                    Payment.paid_at >= since_dt,
                )
            )
        ).scalars()
    )
    post_rows = list(
        (
            await db.execute(
                select(Post.created_at).where(
                    Post.deleted_at.is_(None), Post.created_at >= since_dt
                )
            )
        ).scalars()
    )
    message_7d = await _scalar(
        db,
        select(func.count())
        .select_from(Message)
        .where(
            Message.deleted_at.is_(None) if hasattr(Message, "deleted_at") else True,
            Message.created_at >= now - timedelta(days=7),
        ),
    )

    # --- engagement ------------------------------------------------------
    likes_total = await _scalar(db, select(func.count()).select_from(PostLike))
    comments_total = await _scalar(
        db, select(func.coalesce(func.sum(Post.comment_count), 0))
    )

    # --- location --------------------------------------------------------
    # Users carry no coordinates; the state comes from their organization, which
    # is the only place CartFlow actually knows where someone is. Counts are by
    # state, and users without a campus are grouped as "Unattached" rather than
    # silently dropped — a chart that lies about its denominator is worse than a
    # bar labelled honestly.
    state_rows = (
        await db.execute(
            select(Organization.state, func.count(User.id))
            .select_from(User)
            .outerjoin(Organization, Organization.id == User.organization_id)
            .where(User.deleted_at.is_(None))
            .group_by(Organization.state)
            .order_by(func.count(User.id).desc())
            .limit(10)
        )
    ).all()
    states = [
        {"name": (state or "Unattached"), "value": int(count)}
        for state, count in state_rows
    ]

    return {
        "kpi": {
            "users": users_total,
            "users_7d": users_7d,
            "posts": posts_total,
            "products": products_total,
            "revenue": float(revenue),
            "orders_paid": orders_paid,
            "messages_7d": message_7d,
            "likes": likes_total,
            "comments": comments_total,
        },
        "labels": [d.strftime("%d %b") for d in _buckets(since_day, WINDOW_DAYS)],
        "signups": _daily(signup_rows, since_day, WINDOW_DAYS),
        "posts_series": _daily(post_rows, since_day, WINDOW_DAYS),
        "revenue_series": _daily(paid_rows, since_day, WINDOW_DAYS),
        "states": states,
    }


async def _management_rows(db: AsyncSession) -> dict:
    users = (
        await db.execute(
            select(User)
            .where(User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
            .limit(40)
        )
    ).scalars().all()
    posts = (
        await db.execute(
            select(Post, User)
            .join(User, User.id == Post.author_id)
            .where(Post.deleted_at.is_(None))
            .order_by(Post.created_at.desc())
            .limit(30)
        )
    ).all()
    products = (
        await db.execute(
            select(Product, Organization)
            .join(Organization, Organization.id == Product.organization_id)
            .where(Product.deleted_at.is_(None))
            .order_by(Product.created_at.desc())
            .limit(30)
        )
    ).all()
    return {"users": users, "posts": posts, "products": products}


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if (redirect := _guard(user, request)) is not None:
        return redirect
    if _must_change_password(user):
        return RedirectResponse("/admin/account", status_code=303)

    data = await _dashboard_rows(db)
    # Only the chart series cross into JSON. The tables above are ORM rows, and
    # handing the whole payload to `tojson` is how this page 500s — a Row is not
    # serialisable — so the boundary is drawn here rather than left to the
    # template to remember.
    charts = {
        key: data[key]
        for key in ("labels", "signups", "posts_series", "revenue_series", "states")
    }
    data.update(await _management_rows(db))
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "current_user": user,
            "page_title": "Admin",
            "active_nav": "",
            "data": data,
            "charts": charts,
            "must_change": False,
        },
    )


@router.get("/account", response_class=HTMLResponse)
async def account(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if (redirect := _guard(user, request)) is not None:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="admin/account.html",
        context={
            "current_user": user,
            "page_title": "Admin account",
            "active_nav": "",
            "must_change": _must_change_password(user),
            "error": None,
            "notice": None,
        },
    )


@router.post("/account/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if (redirect := _guard(user, request)) is not None:
        return redirect

    error = None
    if not verify_password(current_password, user.password_hash):
        error = "That is not your current password."
    elif len(new_password) < 10:
        error = "Use at least 10 characters — this account can see every payment."
    elif new_password != confirm_password:
        error = "The two new passwords do not match."
    elif new_password == DEFAULT_PASSWORD:
        error = "Choose something other than the default."

    if error:
        return templates.TemplateResponse(
            request=request,
            name="admin/account.html",
            context={
                "current_user": user,
                "page_title": "Admin account",
                "active_nav": "",
                "must_change": _must_change_password(user),
                "error": error,
                "notice": None,
            },
            status_code=400,
        )

    user.password_hash = hash_password(new_password)
    await db.commit()
    return RedirectResponse("/admin", status_code=303)


# --- user management -----------------------------------------------------


@router.post("/users/{public_id}/status")
async def set_user_status(
    public_id: uuid.UUID,
    request: Request,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Suspend or reinstate an account.

    Self-target is refused: locking yourself out of the only console is a support
    ticket, not a moderation action, and there is no second admin to undo it.
    """
    if (redirect := _guard(user, request)) is not None:
        return redirect
    target = (
        await db.execute(select(User).where(User.public_id == public_id))
    ).scalar_one_or_none()
    if target is None or target.id == user.id:
        return RedirectResponse("/admin", status_code=303)

    allowed = {
        AccountStatus.ACTIVE.value,
        AccountStatus.SUSPENDED.value,
        AccountStatus.RESTRICTED.value,
    }
    if status in allowed:
        target.account_status = AccountStatus(status)
        await db.commit()
    return RedirectResponse("/admin#users", status_code=303)


@router.post("/users/{public_id}/admin")
async def toggle_admin(
    public_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if (redirect := _guard(user, request)) is not None:
        return redirect
    target = (
        await db.execute(select(User).where(User.public_id == public_id))
    ).scalar_one_or_none()
    if target is None or target.id == user.id:
        return RedirectResponse("/admin#users", status_code=303)
    target.is_admin = not target.is_admin
    await db.commit()
    return RedirectResponse("/admin#users", status_code=303)


@router.post("/users/{public_id}/delete")
async def delete_user(
    public_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Soft-delete. The row stays so orders and messages keep a valid author."""
    if (redirect := _guard(user, request)) is not None:
        return redirect
    target = (
        await db.execute(select(User).where(User.public_id == public_id))
    ).scalar_one_or_none()
    if target is None or target.id == user.id:
        return RedirectResponse("/admin#users", status_code=303)
    target.deleted_at = _now()
    target.account_status = AccountStatus.DELETED
    await db.commit()
    return RedirectResponse("/admin#users", status_code=303)


# --- post management -----------------------------------------------------


@router.post("/posts/{public_id}/hide")
async def hide_post(
    public_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Take a post out of the feed without deleting the row a report points at."""
    if (redirect := _guard(user, request)) is not None:
        return redirect
    post = (
        await db.execute(select(Post).where(Post.public_id == public_id))
    ).scalar_one_or_none()
    if post is not None:
        post.status = (
            PostStatus.PUBLISHED
            if post.status == PostStatus.HIDDEN.value
            else PostStatus.HIDDEN
        )
        await db.commit()
    return RedirectResponse("/admin#posts", status_code=303)


@router.post("/posts/{public_id}/delete")
async def delete_post(
    public_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if (redirect := _guard(user, request)) is not None:
        return redirect
    post = (
        await db.execute(select(Post).where(Post.public_id == public_id))
    ).scalar_one_or_none()
    if post is not None:
        post.deleted_at = _now()
        post.status = PostStatus.HIDDEN
        await db.commit()
    return RedirectResponse("/admin#posts", status_code=303)


# --- product management --------------------------------------------------


@router.post("/products/{slug}/update")
async def update_product(
    slug: str,
    request: Request,
    price: int = Form(...),
    stock: int = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Price and stock only.

    The console is for correcting a live listing, not for authoring one: a
    product created here would have no shop owner to answer for it. Negative
    numbers are clamped to zero rather than rejected, because a form that
    bounces is a worse answer to a typo than a value the operator can see.
    """
    if (redirect := _guard(user, request)) is not None:
        return redirect
    product = (
        await db.execute(
            select(Product).where(
                Product.slug == slug, Product.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if product is not None:
        product.price = max(0, price)
        product.stock = max(0, stock)
        await db.commit()
    return RedirectResponse("/admin#products", status_code=303)


@router.post("/products/{slug}/delete")
async def delete_product(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if (redirect := _guard(user, request)) is not None:
        return redirect
    product = (
        await db.execute(
            select(Product).where(
                Product.slug == slug, Product.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if product is not None:
        product.deleted_at = _now()
        product.status = ProductStatus.ARCHIVED
        await db.commit()
    return RedirectResponse("/admin#products", status_code=303)
