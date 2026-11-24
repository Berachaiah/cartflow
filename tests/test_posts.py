"""The posts slice — 0014_posts.

The feed used to be a literal in `home.html`. These tests guard what moving it
into a table bought:

  1. HOME AND THE PROFILE AGREE. One post is one row, so a post that is on Home is
     on its author's profile too, and the count under it is one number.
  2. A LIKE IS A ROW. Toggling writes `post_likes` and moves `posts.like_count`,
     and it is idempotent per account: two taps are one like, not two.
  3. THE TAG IS A LINK, and a slug that does not resolve is dropped rather than
     rendered as a dead chip.
"""

import base64
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.exceptions import ServiceUnavailableError
from app.integrations import cloudinary_client
from app.integrations.cloudinary_client import UploadedImage
from app.models.post import Post, PostLike
from app.services import posts as posts_service
from tests.feed_data import FEED_AUTHORS


async def _signup_and_login(client: AsyncClient, username: str = "poster") -> None:
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Post Er",
            "username": username,
            "email": f"{username}@example.com",
            "password": "Long-enough-pass-2026",
        },
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"identifier": username, "password": "Long-enough-pass-2026"},
    )
    assert r.status_code == 200, r.text


# --- 1. one row, two surfaces -------------------------------------------

async def test_home_renders_the_seeded_posts(sample_feed, client: AsyncClient):
    """Every seeded post reaches Home, by author."""
    r = await client.get("/")
    assert r.status_code == 200, r.text
    for _, display_name, _badge in FEED_AUTHORS:
        assert display_name in r.text, f"post by {display_name} did not reach Home"


async def test_a_post_appears_on_its_authors_profile(sample_feed, client: AsyncClient):
    """The reported gap: "make sure the posts reflect in the profile".

    A post is a row with an author now, so the same photo the feed shows shows up
    in that account's Posts grid. Before this, a post belonged to nobody and could
    not appear anywhere but Home.
    """
    r = await client.get("/@sneakerlab")
    assert r.status_code == 200, r.text
    assert "airflux-side.jpg" in r.text, (
        "the profile's Posts tab does not show the author's post"
    )
    # The grid is photos with their alt text, not captions — so the accessible
    # name is the thing to assert, and it proves the post's own image record
    # (src AND alt) survived the trip from the table to the profile.
    assert "Photo 1 by SneakerLab" in r.text, (
        "the post rendered without its alt text, so a screen reader gets an unlabelled image"
    )


async def test_a_post_is_listed_once_per_profile(sample_feed, db):
    """No duplication: the feed query and the profile query read the same rows."""
    from app.repositories.post import PostRepository

    rows = await PostRepository(db).by_author(sample_feed[1].author_id)
    assert len(rows) == 1, f"one authored post came back as {len(rows)}"


# --- 2. the like is a row ----------------------------------------------

async def test_liking_a_post_writes_a_row_and_moves_the_count(
    sample_feed, client: AsyncClient, db
):
    await _signup_and_login(client)
    post = sample_feed[0]
    before = post.like_count

    r = await client.post(f"/api/posts/{post.public_id}/like")
    assert r.status_code == 200, r.text
    assert r.json() == {"liked": True, "like_count": before + 1}, r.text

    likes = (
        await db.execute(select(PostLike).where(PostLike.post_id == post.id))
    ).scalars().all()
    assert len(likes) == 1, "the like was not written to post_likes"

    # A second tap is an unlike, not a second like: the composite key is the rule.
    again = await client.post(f"/api/posts/{post.public_id}/like")
    assert again.json() == {"liked": False, "like_count": before}, again.text


async def test_liking_twice_is_one_like_per_account(sample_feed, client: AsyncClient, db):
    """Two accounts, two likes — the count follows the rows, not the taps."""
    post = sample_feed[0]
    before = post.like_count

    await _signup_and_login(client, "one")
    assert (await client.post(f"/api/posts/{post.public_id}/like")).status_code == 200
    # Toggling off and on again lands on liked exactly once.
    await client.post(f"/api/posts/{post.public_id}/like")
    final = await client.post(f"/api/posts/{post.public_id}/like")

    assert final.json()["like_count"] == before + 1, final.text
    rows = (
        await db.execute(select(PostLike).where(PostLike.post_id == post.id))
    ).scalars().all()
    assert len(rows) == 1


async def test_liking_an_unknown_post_is_404(client: AsyncClient):
    await _signup_and_login(client)
    r = await client.post(f"/api/posts/{uuid.uuid4()}/like")
    assert r.status_code == 404, r.text


async def test_liking_signed_out_is_rejected(sample_feed, client: AsyncClient):
    r = await client.post(f"/api/posts/{sample_feed[0].public_id}/like")
    assert r.status_code in (401, 403), r.text


# --- 3. tags ------------------------------------------------------------

async def test_a_tagged_product_links_to_its_page(engine, client: AsyncClient):
    """A post tags a slug; the card renders a real link, never a dead chip.

    Uses its own product + post rather than `sample_feed`, because the point is
    the JOIN: the tag is a slug on the post and the name/price/image come from
    the catalogue, so the chip and the product page cannot quote different money.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.models.organization import Organization
    from app.models.product import Product
    from app.models.user import AccountStatus, AccountType, User
    from tests.feed_data import unique_slug

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        org = Organization(
            official_name="Tag Shop",
            short_name="Tag Shop",
            slug=unique_slug("tagshop"),
            country="Nigeria",
            state="Lagos",
            status="active",
        )
        session.add(org)
        await session.flush()
        session.add(
            Product(
                organization_id=org.id,
                name="Tagged Hoodie",
                # Literal, because the post below tags this exact slug and that
                # is the join under test.
                slug="tagged-hoodie",
                category="Fashion",
                price=18500,
                stock=4,
                status="active",
            )
        )
        author = User(
            account_type=AccountType.INDIVIDUAL,
            account_status=AccountStatus.ACTIVE,
            email="tag-author@sample.cartflow.test",
            username="tagauthor",
            username_normalized="tagauthor",
            display_name="Tag Author",
            full_name="Tag Author",
            is_seller=True,
        )
        session.add(author)
        await session.flush()
        # One tag that resolves and one that does not: the second must be dropped
        # silently rather than rendered as a dead link to a 404.
        session.add(
            Post(
                author_id=author.id,
                body="Tagged post #CampusWear",
                images=[],
                tagged_product_slugs=["tagged-hoodie", "archived-long-ago"],
                like_count=3,
            )
        )
        await session.commit()

    r = await client.get("/")
    assert r.status_code == 200, r.text
    assert 'href="/product/tagged-hoodie"' in r.text, (
        "a post's tagged product did not render as a link to its page"
    )
    assert "archived-long-ago" not in r.text, (
        "a tag whose product does not exist was rendered — that is a link to a 404"
    )


# --- 4. publishing a post ------------------------------------------------
#
# The composer is the feature these guard: a post is written by a real account
# through the same endpoint the browser calls, and a photo goes through the
# shared media pipeline (`app/services/media.py`) rather than a second uploader
# written for posts.

# A 1x1 PNG — enough for the magic-byte check in `media_service.read_image_upload`,
# not an image anyone has to look at.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def test_the_composer_publishes_a_post(client: AsyncClient):
    """The caption reaches Home, under the account that wrote it."""
    await _signup_and_login(client, "composer")
    r = await client.post(
        "/api/posts", data={"body": "Restocked the Seraph tees today."}
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["caption"] == "Restocked the Seraph tees today."
    assert payload["handle"] == "composer", "the post was not attributed to its author"

    home = await client.get("/")
    assert "Restocked the Seraph tees today." in home.text


async def test_an_empty_post_is_refused(client: AsyncClient):
    await _signup_and_login(client, "empty")
    r = await client.post("/api/posts", data={"body": "   "})
    assert r.status_code == 422, r.text


async def test_an_oversized_post_is_refused(client: AsyncClient):
    await _signup_and_login(client, "wordy")
    r = await client.post("/api/posts", data={"body": "x" * 2001})
    assert r.status_code == 422, r.text


async def test_posting_requires_a_session(client: AsyncClient):
    r = await client.post("/api/posts", data={"body": "not signed in"})
    assert r.status_code == 401, r.text


async def test_the_composer_only_renders_for_a_signed_in_account(client: AsyncClient):
    assert 'id="composerForm"' not in (await client.get("/")).text
    await _signup_and_login(client, "composer2")
    assert 'id="composerForm"' in (await client.get("/")).text


async def test_a_photo_post_is_uploaded_under_the_posts_folder(
    client: AsyncClient, monkeypatch
):
    """A photo post goes through Cloudinary and renders a delivery URL.

    The upload is stubbed: this test is about the wiring (folder, subfolder,
    stored URL shape), and a suite that uploads to a real account would fail on
    a plane and litter the account on every run.
    """
    await _signup_and_login(client, "photoposter")
    captured: dict = {}

    async def fake_upload(data, *, folder, public_id, filename="upload"):
        captured.update(
            folder=folder, public_id=public_id, size=len(data), filename=filename
        )
        return UploadedImage(
            public_id=f"{folder}/{public_id}",
            secure_url="https://res.cloudinary.com/dzgslgj16/image/upload/x.png",
            width=1,
            height=1,
            format="png",
            bytes=len(data),
        )

    monkeypatch.setattr(cloudinary_client, "upload_image", fake_upload)

    r = await client.post(
        "/api/posts",
        data={"body": "New colourway"},
        files={"file": ("tee.png", PNG_1PX, "image/png")},
    )
    assert r.status_code == 201, r.text

    assert captured["folder"].endswith("/posts"), captured
    assert captured["size"] == len(PNG_1PX)
    assert captured["filename"] == "tee.png"

    media = r.json()["media"]
    assert len(media) == 1, media
    assert media[0]["src"].startswith("https://res.cloudinary.com/"), media[0]


async def test_a_photo_post_is_503_when_the_host_is_not_configured(
    client: AsyncClient, monkeypatch
):
    """No Cloudinary credentials is a server state, not a bad file — so 503.

    The composer hides the photo control in that state; this is the backstop for
    a client that sends a file anyway, and it must not read as "your image was
    rejected".
    """
    await _signup_and_login(client, "nohost")

    def unavailable():
        raise ServiceUnavailableError("Photo uploads aren't set up on this server yet.")

    monkeypatch.setattr(posts_service.media_service, "require_media_enabled", unavailable)

    r = await client.post(
        "/api/posts",
        data={"body": "has a photo"},
        files={"file": ("a.png", PNG_1PX, "image/png")},
    )
    assert r.status_code == 503, r.text
