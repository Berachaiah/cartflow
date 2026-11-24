"""Appearance: three preferences, one control, and where it appears.

The theme used to be a two-state toggle (light/dark) with the switch living in
the sidebar, the mobile bar and the footer. It is now System / Light / Dark, in
Settings and on the signed-out screens, driven by one partial and one piece of
state in base.html.

What is worth guarding, because each failure is invisible on the page that
causes it:

1. THE PREFERENCE IS NOT THE RESULT. `cartflow-theme` stores 'light', 'dark' or
   'system'; `data-theme` holds what that resolves to. If 'system' were ever
   written into data-theme the palette would fall back to dark regardless of the
   device, and if the resolved value were written back to storage, "follow the
   device" could never be chosen again.
2. THE DEFAULT IS SYSTEM. An installed app that ignores the phone's appearance
   setting looks broken next to the rest of the home screen.
3. BOTH SURFACES CARRY IT. /login is the first screen of a fresh install, and
   Settings is where the choice is expected to live.
"""

from pathlib import Path

from httpx import AsyncClient

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
BASE = (TEMPLATES / "base.html").read_text(encoding="utf-8")
SWITCH = (TEMPLATES / "partials" / "theme_switch.html").read_text(encoding="utf-8")
SETTINGS = (TEMPLATES / "settings.html").read_text(encoding="utf-8")


async def _signup_and_login(client: AsyncClient, username: str = "themer") -> None:
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Theme Er",
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


# --- 1. preference vs. result -------------------------------------------


def test_the_three_preferences_are_the_only_stored_values():
    assert "const CF_THEME_PREFS = ['light', 'dark', 'system'];" in BASE
    assert "localStorage.setItem(CF_THEME_KEY, pref)" in BASE


def test_system_resolves_through_the_device_not_storage():
    """`system` must be decided by matchMedia and never stored as a palette."""
    assert "(prefers-color-scheme: dark)" in BASE
    assert "cfPref === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches" in BASE


def test_rendering_a_page_does_not_write_the_choice():
    """An absent key has to keep meaning "hasn't chosen", or the default can never
    change for anyone who has already opened the app."""
    head, _, tail = BASE.partition("</script>")
    assert "localStorage.setItem" not in head, (
        "the pre-paint script must only READ the preference"
    )
    assert "cfSetTheme" in tail


# --- 2. the control -----------------------------------------------------


async def test_the_switch_offers_all_three_with_icons(client: AsyncClient):
    r = await client.get("/login")
    assert r.status_code == 200, r.text
    for pref, icon in (
        ("system", "desktop_windows"),
        ("light", "light_mode"),
        ("dark", "dark_mode"),
    ):
        assert f'data-cf-theme="{pref}"' in r.text, pref
        assert icon in r.text, f"{pref} has no icon"
    assert 'aria-label="Appearance"' in r.text


async def test_each_segment_is_a_button_with_a_pressed_state():
    """Buttons, not links: nothing navigates, and aria-pressed is what tells a
    screen reader which one is on."""
    assert SWITCH.count('type="button"') == 3
    # Counted as "false" because the markup ships unselected: base.html's
    # cfSyncThemeSwitches() flips the pressed one on load.
    assert SWITCH.count('aria-pressed="false"') == 3
    assert 'role="group"' in SWITCH


# --- 3. both surfaces ---------------------------------------------------


async def test_the_login_page_carries_the_switch(client: AsyncClient):
    r = await client.get("/login")
    assert r.status_code == 200
    assert 'class="cf-theme-switch' in r.text


async def test_settings_carries_the_switch_and_no_binary_toggle():
    assert '{{ theme_switch() }}' in SETTINGS
    assert "themeRowBtn" not in SETTINGS, (
        "the old light/dark button is still in Settings — two theme controls would disagree"
    )


async def test_settings_renders_the_switch_for_a_signed_in_account(client: AsyncClient):
    await _signup_and_login(client, "settings-themer")
    r = await client.get("/settings")
    assert r.status_code == 200, r.text
    assert 'class="cf-theme-switch' in r.text
    assert 'data-cf-theme="system"' in r.text
