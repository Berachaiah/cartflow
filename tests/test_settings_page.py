"""
Render tests for /settings — the private counterpart to /@handle.

This page had never been rendered by a test, which is how a `| string` filter on
an enum comparison hid the graduation row from every student account for as long
as it existed (see `is_student` in the template). So the rules guarded here are
the ones that are invisible from reading the markup:

  1. Signed out is a REDIRECT to /login?next=/settings, not a 401 and not an
     anonymous render — there is no useful public version of "your settings".
  2. The selling block is gated on an OWNED organizations row, not on
     `users.is_seller`: a non-seller gets the two-field form, a seller gets the
     Business Hub link and no form.
  3. `is_student` must actually be true for a student. AccountType is a
     (str, Enum), so `== 'student'` works and `| string == 'student'` never can.
  4. Full name is labelled private and is the only one of the three names that
     is absent from the public profile.
  5. Nothing on this page fakes a save: every control maps to an endpoint that
     exists.

Exercises the real ASGI app on in-memory SQLite (see conftest).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization

PASSWORD = "password123"
UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")


async def _seed_school(db: AsyncSession, official_name: str, short_name: str) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        organization_type_id=UNIVERSITY_TYPE_ID,
        official_name=official_name,
        short_name=short_name,
        slug=short_name.lower(),
        country="Nigeria",
        state="Lagos",
        status="active",
    )
    db.add(org)
    await db.commit()
    return org


async def _signup(client: AsyncClient, username: str, **extra) -> None:
    payload = {
        "role": extra.pop("role", "individual"),
        "full_name": extra.pop("full_name", f"{username.title()} Tester"),
        "username": username,
        "email": f"{username}@example.com",
        "password": PASSWORD,
        **extra,
    }
    r = await client.post("/api/auth/signup", json=payload)
    assert r.status_code == 201, r.text


async def _login(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text


# --- access --------------------------------------------------------------

async def test_signed_out_redirects_to_login_with_a_return_path(client: AsyncClient):
    """A 401 would be a dead end and an anonymous render would be a lie. The
    `next=` is what makes logging in from here land back here."""
    r = await client.get("/settings")
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/login?next=/settings"


async def test_signed_in_renders(client: AsyncClient):
    await _signup(client, "ada", full_name="Ada Lovelace")
    await _login(client, "ada")

    r = await client.get("/settings")
    assert r.status_code == 200, r.text
    body = r.text
    assert 'id="identityForm"' in body
    assert 'id="logoutBtn"' in body
    # Settings is navigated INTO, so it has a back arrow rather than the tab bar's
    # idea of a root page.
    assert 'id="settingsBack"' in body


# --- the three names -----------------------------------------------------

async def test_all_three_name_fields_are_present_and_prefilled(client: AsyncClient):
    await _signup(client, "ada", full_name="Ada Lovelace")
    await _login(client, "ada")
    r = await client.patch("/api/users/me", json={"display_name": "Ada L.", "bio": "hi"})
    assert r.status_code == 200, r.text

    body = (await client.get("/settings")).text
    assert 'id="fUsername"' in body and 'value="ada"' in body
    assert 'id="fDisplayName"' in body and 'value="Ada L."' in body
    assert 'id="fFullName"' in body and 'value="Ada Lovelace"' in body
    assert 'id="fBio"' in body and ">hi</textarea>" in body


async def test_full_name_is_labelled_private_and_stays_off_the_profile(
    client: AsyncClient,
):
    """The whole reason full_name is editable here and nowhere else: it is for
    receipts and delivery, and the profile must never print it."""
    await _signup(client, "ada", full_name="Ada Lovelace")
    await _login(client, "ada")
    # Give the public identity a different value so the assertion below can't pass
    # by accident.
    await client.patch("/api/users/me", json={"display_name": "ada builds"})

    settings_body = (await client.get("/settings")).text
    assert ">Private<" in settings_body
    assert "Ada Lovelace" in settings_body

    profile_body = (await client.get("/@ada")).text
    assert "ada builds" in profile_body
    assert "Ada Lovelace" not in profile_body


async def test_username_change_is_warned_about_before_it_is_offered(
    client: AsyncClient,
):
    """There is no username_history table, so a rename is irreversible and
    unredirected. Saying so next to the field is the whole mitigation."""
    await _signup(client, "ada")
    await _login(client, "ada")

    body = (await client.get("/settings")).text
    assert "the old link" in body
    assert "someone else can take it" in body


# --- selling -------------------------------------------------------------

async def test_non_seller_gets_the_two_field_upgrade_form(client: AsyncClient):
    """Two fields, because that is all POST /api/auth/business/upgrade needs —
    the point of moving this off the profile was that it costs two taps."""
    await _signup(client, "ada")
    await _login(client, "ada")

    body = (await client.get("/settings")).text
    assert 'id="sellForm"' in body
    assert 'id="sellName"' in body
    assert 'id="sellState"' in body
    assert "Start selling" in body
    # And no Hub row pretending there's a business to manage. (The desktop rail
    # in base.html links /dashboard for everyone — that route renders its own
    # "start selling" state — so this checks the settings row specifically.)
    assert "Business Hub · products" not in body


async def test_seller_gets_the_hub_link_and_no_upgrade_form(client: AsyncClient):
    await _signup(
        client,
        "shop",
        role="brand",
        full_name="Shop Owner",
        business_name="Hat Depot",
        state="Lagos",
    )
    await _login(client, "shop")

    body = (await client.get("/settings")).text
    assert 'id="sellForm"' not in body
    assert "Business Hub · products" in body
    assert "Hat Depot" in body


async def test_upgrading_from_settings_flips_the_page(client: AsyncClient):
    """End to end through the real endpoint: the form on this page is what turns
    an account into a seller, so the page it renders afterwards must have
    changed."""
    await _signup(client, "ada")
    await _login(client, "ada")
    assert 'id="sellForm"' in (await client.get("/settings")).text

    r = await client.post(
        "/api/auth/business/upgrade",
        json={"business_name": "Ada Wares", "state": "Lagos"},
    )
    assert r.status_code in (200, 201), r.text

    body = (await client.get("/settings")).text
    assert 'id="sellForm"' not in body
    assert "Ada Wares" in body


# --- graduation ----------------------------------------------------------

async def test_student_sees_the_graduation_toggle(db, client: AsyncClient):
    """The regression this file was written for. `is_student` used to run the
    enum through Jinja's `string` filter, which yields 'AccountType.STUDENT' and
    never equals 'student' — so this row silently never rendered."""
    school = await _seed_school(db, "University of Lagos", "UNILAG")
    await _signup(
        client,
        "kem",
        role="student",
        full_name="Kem Student",
        organization_id=str(school.id),
    )
    await _login(client, "kem")

    body = (await client.get("/settings")).text
    assert 'id="gradToggle"' in body
    assert "I've graduated" in body
    # NO badge, pill or label is rendered for graduation anywhere in the product.
    assert "Alumni" not in body
    assert "Graduate<" not in body


async def test_non_student_has_no_graduation_toggle(client: AsyncClient):
    await _signup(client, "ada", role="individual")
    await _login(client, "ada")

    body = (await client.get("/settings")).text
    assert 'id="gradToggle"' not in body


# --- account -------------------------------------------------------------

async def test_email_is_shown_with_its_verification_state(client: AsyncClient):
    """Read-only on purpose: changing an address needs a verification
    round-trip that has no endpoint yet, so the page shows the fact plus the one
    action that does exist."""
    await _signup(client, "ada")
    await _login(client, "ada")

    body = (await client.get("/settings")).text
    assert "ada@example.com" in body
    # Fresh signups are unverified, so the resend control is the live one.
    assert 'id="resendVerifyBtn"' in body
    assert "verification round-trip" in body


async def test_password_change_points_at_the_flow_that_exists(client: AsyncClient):
    """There is no old-password → new-password endpoint. The reset flow IS the
    change flow, so the row links there instead of opening a form that can't
    save."""
    await _signup(client, "ada")
    await _login(client, "ada")

    body = (await client.get("/settings")).text
    assert 'href="/forgot-password"' in body
    assert "Change password" in body


async def test_unimplemented_preferences_are_named_not_switched(client: AsyncClient):
    """A toggle with no table behind it forgets every change. Only the theme
    control — which is real, backed by localStorage — is rendered as a control.

    That control is the three-way Appearance switch from
    `partials/theme_switch.html` (system / light / dark), not the single
    `themeRowBtn` this test used to look for: a binary toggle cannot express
    "follow the device", and the auth screens already render the same partial.
    """
    await _signup(client, "ada")
    await _login(client, "ada")

    body = (await client.get("/settings")).text
    assert 'class="cf-theme-switch' in body
    for pref in ("system", "light", "dark"):
        assert f'data-cf-theme="{pref}"' in body, f"the Appearance control lost its {pref} segment"
    # Graduation is the page's only real switch and it's student-gated, so a
    # non-student's markup carries no toggle element at all. (Matched on the
    # button id rather than counting role="switch" — the CSS comment explaining
    # the switch is rendered into the page's <style> block and contains that
    # string too.)
    assert 'id="gradToggle"' not in body
    assert "switches that forget" in body
