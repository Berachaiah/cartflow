"""
Follow-graph tests — service rules first, then the HTTP surface.

`user_follows` shipped in the baseline migration and sat unused until Profiles
needed it, so these tests are the first thing that has ever exercised it. The
behaviours guarded here are the ones a caller can't infer from the schema:

  - follow / unfollow are idempotent (the button is a toggle, not a command)
  - counts ignore soft-deleted accounts (rows outlive the user they point at)
  - suspended and soft-deleted handles 404 exactly like handles that never
    existed, so no response confirms a hidden account
  - list responses never carry an email address

Runs against in-memory SQLite via the shared fixtures (see conftest).
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.user import AccountStatus, AccountType, User, UserFollow
from app.services import follow as follow_service


async def _make_user(db: AsyncSession, username: str, **extra) -> User:
    """Insert a minimal usable account. Deliberately bypasses signup — these
    tests are about the follow graph, not about how the row got there."""
    user = User(
        account_type=extra.pop("account_type", AccountType.INDIVIDUAL),
        account_status=extra.pop("account_status", AccountStatus.ACTIVE),
        email=extra.pop("email", f"{username}@example.com"),
        password_hash=None,
        username=username,
        username_normalized=username.lower(),
        display_name=extra.pop("display_name", f"{username.title()} Person"),
        **extra,
    )
    db.add(user)
    await db.flush()
    return user


async def _edge_count(db: AsyncSession) -> int:
    return len((await db.execute(select(UserFollow))).all())


# --- service: writes -----------------------------------------------------

async def test_follow_creates_edge_and_counts_it(db: AsyncSession):
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")

    state = await follow_service.follow_user(db, follower=alice, username="bob")

    assert state.following is True
    assert state.follower_count == 1
    assert state.changed is True
    assert await _edge_count(db) == 1


async def test_follow_twice_is_idempotent(db: AsyncSession):
    """A double-tapped button must not raise, and must not double-count. The
    second insert is swallowed by the savepoint in _insert_follow."""
    alice = await _make_user(db, "alice")
    await _make_user(db, "bob")

    first = await follow_service.follow_user(db, follower=alice, username="bob")
    second = await follow_service.follow_user(db, follower=alice, username="bob")

    assert first.changed is True
    assert second.changed is False
    assert second.following is True
    assert second.follower_count == 1
    assert await _edge_count(db) == 1


async def test_follow_survives_a_racing_duplicate(db: AsyncSession):
    """The savepoint must leave the surrounding transaction usable after the
    IntegrityError — otherwise get_db's commit fails and the user sees a 500
    for a follow that actually succeeded."""
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")

    db.add(UserFollow(follower_id=alice.id, following_id=bob.id))
    await db.flush()

    state = await follow_service.follow_user(db, follower=alice, username="bob")
    assert state.changed is False

    # The session is still healthy: a further write goes through.
    await _make_user(db, "carol")
    assert await _edge_count(db) == 1


async def test_unfollow_removes_edge_and_is_idempotent(db: AsyncSession):
    alice = await _make_user(db, "alice")
    await _make_user(db, "bob")

    await follow_service.follow_user(db, follower=alice, username="bob")

    first = await follow_service.unfollow_user(db, follower=alice, username="bob")
    second = await follow_service.unfollow_user(db, follower=alice, username="bob")

    assert first.following is False and first.changed is True
    assert second.following is False and second.changed is False
    assert second.follower_count == 0
    assert await _edge_count(db) == 0


async def test_cannot_follow_self(db: AsyncSession):
    alice = await _make_user(db, "alice")
    with pytest.raises(ValidationAppError):
        await follow_service.follow_user(db, follower=alice, username="alice")


async def test_follow_is_case_insensitive(db: AsyncSession):
    """`/@ALICE` and `/@alice` are the same account (usernames are matched on
    username_normalized), so following either must hit the same row."""
    alice = await _make_user(db, "Alice")
    bob = await _make_user(db, "bob")

    state = await follow_service.follow_user(db, follower=bob, username="ALICE")
    assert state.follower_count == 1

    stats = await follow_service.get_profile_stats(
        db, user_id=alice.id, viewer_id=bob.id
    )
    assert stats.is_following is True


# --- service: target resolution -----------------------------------------

async def test_unknown_handle_is_not_found(db: AsyncSession):
    with pytest.raises(NotFoundError):
        await follow_service.resolve_public_user(db, username="nobodyhere")


async def test_malformed_handle_is_not_found_without_a_query(db: AsyncSession):
    """A handle that can't be a username is rejected on the pattern, so an
    oversized path segment never reaches the database."""
    for bad in ("ab", "x" * 400, "has space", "semi;colon"):
        with pytest.raises(NotFoundError):
            await follow_service.resolve_public_user(db, username=bad)


async def test_suspended_and_soft_deleted_handles_are_not_found(db: AsyncSession):
    await _make_user(db, "suspended", account_status=AccountStatus.SUSPENDED)
    await _make_user(db, "gone", deleted_at=datetime.now(timezone.utc))
    await _make_user(db, "restricted", account_status=AccountStatus.RESTRICTED)

    for hidden in ("suspended", "gone"):
        with pytest.raises(NotFoundError):
            await follow_service.resolve_public_user(db, username=hidden)

    # RESTRICTED limits what an account can do, not whether it exists.
    assert (
        await follow_service.resolve_public_user(db, username="restricted")
    ).username == "restricted"


# --- service: reads ------------------------------------------------------

async def test_stats_are_zero_for_a_fresh_account(db: AsyncSession):
    alice = await _make_user(db, "alice")
    stats = await follow_service.get_profile_stats(db, user_id=alice.id)
    assert (stats.followers, stats.following, stats.is_following) == (0, 0, False)


async def test_stats_signed_out_never_claims_a_follow(db: AsyncSession):
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    await follow_service.follow_user(db, follower=bob, username="alice")

    stats = await follow_service.get_profile_stats(db, user_id=alice.id, viewer_id=None)
    assert stats.followers == 1
    assert stats.is_following is False


async def test_counts_exclude_soft_deleted_accounts(db: AsyncSession):
    """Unfollowing is a hard delete but account deletion is soft, so the edge
    outlives the account. A count that ignored deleted_at would inflate
    forever."""
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    carol = await _make_user(db, "carol")

    await follow_service.follow_user(db, follower=bob, username="alice")
    await follow_service.follow_user(db, follower=carol, username="alice")
    await follow_service.follow_user(db, follower=alice, username="bob")

    bob.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    alice_stats = await follow_service.get_profile_stats(db, user_id=alice.id)
    assert alice_stats.followers == 1        # carol only; bob is gone
    assert alice_stats.following == 0        # bob is gone


async def test_lists_return_the_right_people_in_newest_first_order(db: AsyncSession):
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    carol = await _make_user(db, "carol")

    await follow_service.follow_user(db, follower=bob, username="alice")
    await follow_service.follow_user(db, follower=carol, username="alice")
    await follow_service.follow_user(db, follower=alice, username="carol")

    followers = await follow_service.list_followers(db, user_id=alice.id)
    assert followers.total == 2
    assert {r.user.username for r in followers.items} == {"bob", "carol"}

    following = await follow_service.list_following(db, user_id=alice.id)
    assert following.total == 1
    assert following.items[0].user.username == "carol"


async def test_list_rows_carry_the_viewers_own_follow_state(db: AsyncSession):
    """The Followers sheet renders a Follow button per row; without this batch
    annotation every row would read "Follow" even for accounts you follow."""
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    carol = await _make_user(db, "carol")

    await follow_service.follow_user(db, follower=bob, username="alice")
    await follow_service.follow_user(db, follower=carol, username="alice")
    # The viewer (bob) follows carol but not himself.
    await follow_service.follow_user(db, follower=bob, username="carol")

    page = await follow_service.list_followers(db, user_id=alice.id, viewer_id=bob.id)
    by_name = {r.user.username: r for r in page.items}

    assert by_name["carol"].is_following is True
    assert by_name["bob"].is_self is True
    assert by_name["bob"].is_following is False


async def test_list_pagination_slices_without_losing_the_total(db: AsyncSession):
    alice = await _make_user(db, "alice")
    for i in range(5):
        follower = await _make_user(db, f"fan{i}")
        await follow_service.follow_user(db, follower=follower, username="alice")

    first = await follow_service.list_followers(db, user_id=alice.id, limit=2)
    second = await follow_service.list_followers(db, user_id=alice.id, limit=2, offset=2)

    assert first.total == second.total == 5
    assert len(first.items) == len(second.items) == 2
    assert {r.user.id for r in first.items}.isdisjoint({r.user.id for r in second.items})


async def test_lists_skip_soft_deleted_accounts(db: AsyncSession):
    alice = await _make_user(db, "alice")
    bob = await _make_user(db, "bob")
    await follow_service.follow_user(db, follower=bob, username="alice")

    bob.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    page = await follow_service.list_followers(db, user_id=alice.id)
    assert page.total == 0
    assert page.items == []


# --- HTTP surface --------------------------------------------------------
# The `db` and `client` fixtures share one engine, so an account created over
# the API is visible to a direct query and vice versa.

PASSWORD = "password123"


async def _signup(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": f"{username.title()} Tester",
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
        },
    )
    assert r.status_code == 201, r.text


async def _login(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


async def test_follow_endpoint_requires_a_session(client: AsyncClient):
    await _signup(client, "target")
    r = await client.post("/api/users/target/follow")
    assert r.status_code == 401, r.text


async def test_follow_endpoint_round_trips(db, client: AsyncClient):
    await _signup(client, "target")
    await _signup(client, "viewer")
    await _login(client, "viewer")

    r = await client.post("/api/users/target/follow")
    assert r.status_code == 200, r.text
    assert r.json() == {"following": True, "follower_count": 1, "changed": True}

    # Same request again: still 200, still one follower.
    r = await client.post("/api/users/target/follow")
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is False
    assert r.json()["follower_count"] == 1

    r = await client.request("DELETE", "/api/users/target/follow")
    assert r.status_code == 200, r.text
    assert r.json() == {"following": False, "follower_count": 0, "changed": True}

    # And the edge really is gone from the table, not just from the response.
    assert await _edge_count(db) == 0


async def test_follow_endpoint_rejects_self_follow(client: AsyncClient):
    await _signup(client, "viewer")
    await _login(client, "viewer")

    r = await client.post("/api/users/viewer/follow")
    assert r.status_code == 422, r.text
    assert "yourself" in r.json()["error"]["message"]


async def test_follow_endpoint_404s_on_hidden_and_unknown_handles(
    db, client: AsyncClient
):
    await _signup(client, "viewer")
    await _login(client, "viewer")
    await _make_user(db, "suspended", account_status=AccountStatus.SUSPENDED)
    await db.commit()

    for handle in ("nobodyhere", "suspended"):
        r = await client.post(f"/api/users/{handle}/follow")
        assert r.status_code == 404, f"{handle}: {r.text}"


async def test_followers_endpoint_shape_and_pagination(client: AsyncClient):
    await _signup(client, "target")
    for i in range(3):
        await _signup(client, f"fan{i}")
        await _login(client, f"fan{i}")
        r = await client.post("/api/users/target/follow")
        assert r.status_code == 200, r.text

    r = await client.get("/api/users/target/followers?limit=2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    r = await client.get("/api/users/target/followers?limit=2&offset=2")
    assert len(r.json()["items"]) == 1


async def test_follow_lists_never_leak_an_email(client: AsyncClient):
    """PublicUserOut exists for exactly this reason — UserOut carries `email`
    and must never reach somebody else's profile."""
    await _signup(client, "target")
    await _signup(client, "viewer")
    await _login(client, "viewer")
    await client.post("/api/users/target/follow")

    r = await client.get("/api/users/target/followers")
    assert r.status_code == 200, r.text
    assert "email" not in r.json()["items"][0]
    assert "viewer@example.com" not in r.text


async def test_follow_list_annotates_the_viewers_own_state(client: AsyncClient):
    await _signup(client, "target")
    await _signup(client, "viewer")
    await _signup(client, "other")

    await _login(client, "other")
    await client.post("/api/users/target/follow")

    await _login(client, "viewer")
    await client.post("/api/users/target/follow")
    await client.post("/api/users/other/follow")

    r = await client.get("/api/users/target/followers")
    rows = {item["username"]: item for item in r.json()["items"]}
    assert rows["other"]["is_following"] is True     # viewer follows other
    assert rows["viewer"]["is_self"] is True
    assert rows["viewer"]["is_following"] is False


async def test_follow_lists_are_readable_signed_out(client: AsyncClient):
    await _signup(client, "target")
    await _signup(client, "viewer")
    await _login(client, "viewer")
    await client.post("/api/users/target/follow")
    await client.post("/api/auth/logout")

    r = await client.get("/api/users/target/followers")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    # No session → no claim about a relationship, rather than a missing key.
    assert r.json()["items"][0]["is_following"] is False


# --- PATCH /api/users/me -------------------------------------------------

async def test_edit_profile_updates_name_and_bio(db, client: AsyncClient):
    await _signup(client, "viewer")
    await _login(client, "viewer")

    r = await client.patch(
        "/api/users/me", json={"display_name": "  Ada L.  ", "bio": " builds things "}
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Ada L."
    assert r.json()["bio"] == "builds things"

    fetched = await db.execute(
        select(User).where(User.username_normalized == "viewer")
    )
    saved = fetched.scalars().one()
    assert (saved.display_name, saved.bio) == ("Ada L.", "builds things")


async def test_edit_profile_leaves_absent_fields_alone_but_clears_an_empty_bio(
    client: AsyncClient,
):
    """An absent key means "don't touch"; an explicitly empty bio means "clear
    it". Collapsing the two would make deleting a bio impossible."""
    await _signup(client, "viewer")
    await _login(client, "viewer")

    await client.patch("/api/users/me", json={"display_name": "Ada", "bio": "hello"})

    r = await client.patch("/api/users/me", json={"display_name": "Ada Lovelace"})
    assert r.json()["bio"] == "hello"          # untouched

    r = await client.patch("/api/users/me", json={"bio": ""})
    assert r.json()["bio"] is None             # cleared
    assert r.json()["display_name"] == "Ada Lovelace"


async def test_edit_profile_rejects_bad_input_and_applies_username(
    db, client: AsyncClient
):
    await _signup(client, "viewer")
    await _login(client, "viewer")

    assert (await client.patch("/api/users/me", json={})).status_code == 422
    assert (
        await client.patch("/api/users/me", json={"display_name": "   "})
    ).status_code == 422
    assert (
        await client.patch("/api/users/me", json={"bio": "x" * 501})
    ).status_code == 422

    # The handle IS editable now (Settings → Identity), so a payload carrying one
    # applies it rather than silently dropping it. This assertion used to say the
    # opposite; it was written when handles were immutable.
    r = await client.patch(
        "/api/users/me", json={"display_name": "Ada", "username": "somethingelse"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "somethingelse"

    # …and the old URL stops resolving, which is the cost the settings form warns
    # about before saving. Nothing records that `viewer` used to be this account.
    assert (await client.get("/@viewer")).status_code == 404
    assert (await client.get("/@somethingelse")).status_code == 200


async def test_edit_profile_requires_a_session(client: AsyncClient):
    r = await client.patch("/api/users/me", json={"display_name": "Nobody"})
    assert r.status_code == 401, r.text
