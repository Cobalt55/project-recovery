"""Static accessibility and generic-product contract checks for rendered pages."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment

playwright = pytest.importorskip("playwright.sync_api")
Page = playwright.Page
sync_playwright = playwright.sync_playwright

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "project_recovery" / "templates"
STATIC = ROOT / "src" / "project_recovery" / "static"


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _render_workspace_shell() -> str:
    """Render the real shell without route or database dependencies."""
    shell = _template("base.html")
    shell = re.sub(r'<link rel="stylesheet" href="/static/app.css">', "", shell)
    shell = re.sub(r'<script src="/static/app.js" defer></script>', "", shell)
    navigation = [
        SimpleNamespace(label="Chat", href="/chat", active=True, group="workspace"),
        SimpleNamespace(label="Settings", href="/settings", active=False, group="workspace"),
        SimpleNamespace(label="Users", href="/admin/users", active=False, group="admin"),
    ]
    return (
        Environment(autoescape=True)
        .from_string(shell)
        .render(
            user=SimpleNamespace(email="admin@example.test", force_password_change=False),
            csrf_token="test-csrf",
            navigation=navigation,
        )
    )


@pytest.fixture
def workspace_page() -> Page:
    """Exercise the shipped shell assets in Chromium without adding test-only frontend code."""
    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 720})
        page.set_content(_render_workspace_shell())
        page.add_style_tag(content=(STATIC / "app.css").read_text(encoding="utf-8"))
        page.add_script_tag(content=(STATIC / "app.js").read_text(encoding="utf-8"))
        yield page
        browser.close()


def test_shared_shell_has_landmarks_and_keyboard_focus_targets() -> None:
    """Every authenticated page inherits a named navigation and focusable main landmark."""
    shell = _template("base.html")

    assert '<html lang="en">' in shell
    assert '<aside class="side-rail" aria-label="Application">' in shell
    assert '<nav aria-label="Main navigation">' in shell
    assert '<main id="main-content">' in shell
    assert 'aria-current="page"' in shell
    assert 'rel="stylesheet"' in shell


def test_shared_shell_has_an_accessible_responsive_drawer() -> None:
    """Removing responsive navigation controls must not strand mobile keyboard users."""
    shell = _template("base.html")
    css = (ROOT / "src" / "project_recovery" / "static" / "app.css").read_text(encoding="utf-8")

    assert 'aria-label="Open navigation"' in shell
    assert 'aria-label="Close navigation"' in shell
    assert "data-drawer-backdrop" in shell
    assert 'aria-modal="true"' in shell
    assert "ADMIN" not in shell
    assert "@media (max-width: 900px)" in css


def test_workspace_controls_and_navigation_meet_the_44px_target(
    workspace_page: Page,
) -> None:
    """Shrinking logout or navigation controls below the approved touch target must fail."""
    controls = workspace_page.locator(".button, .nav-link, .menu-button")

    for index in range(controls.count()):
        minimum_height = controls.nth(index).evaluate(
            "element => Number.parseFloat(getComputedStyle(element).minHeight)"
        )
        assert minimum_height >= 44


def test_workspace_drawer_handles_keyboard_and_backdrop(workspace_page: Page) -> None:
    """A drawer that leaks focus or fails to restore its opener must fail this browser contract."""
    opener = workspace_page.locator("[data-drawer-open]")
    drawer = workspace_page.locator("[data-drawer]")
    backdrop = workspace_page.locator("[data-drawer-backdrop]")
    close_button = workspace_page.locator("[data-drawer-close]")
    first_link = drawer.locator("a[href]").first
    last_link = drawer.locator("a[href]").last

    assert drawer.is_hidden()
    assert opener.get_attribute("aria-expanded") == "false"
    opener.click()

    assert not drawer.is_hidden()
    assert drawer.get_attribute("aria-hidden") == "false"
    assert backdrop.get_attribute("aria-hidden") == "false"
    assert opener.get_attribute("aria-expanded") == "true"
    assert workspace_page.evaluate("document.body.classList.contains('drawer-open')")
    assert close_button.evaluate("element => document.activeElement === element")

    first_link.focus()
    workspace_page.keyboard.press("Shift+Tab")
    assert last_link.evaluate("element => document.activeElement === element")
    workspace_page.keyboard.press("Tab")
    assert first_link.evaluate("element => document.activeElement === element")

    workspace_page.keyboard.press("Escape")
    assert drawer.is_hidden()
    assert opener.get_attribute("aria-expanded") == "false"
    assert not workspace_page.evaluate("document.body.classList.contains('drawer-open')")
    assert opener.evaluate("element => document.activeElement === element")

    opener.click()
    workspace_page.mouse.click(380, 20)
    assert drawer.is_hidden()
    assert opener.evaluate("element => document.activeElement === element")


def test_login_and_settings_forms_have_explicit_labels_and_autocomplete() -> None:
    """Credential forms expose their purpose to keyboard and assistive-technology users."""
    login = _template("login.html")
    settings = _template("settings.html")

    assert '<main class="auth-panel">' in login
    assert '<label>Email<input name="email" type="email"' in login
    assert 'autocomplete="email"' in login
    assert 'autocomplete="current-password"' in login
    assert 'role="alert"' in login
    assert 'autocomplete="new-password"' in settings
    assert 'minlength="20"' in settings


def test_named_admin_pages_use_heading_landmarks_and_safe_generic_language() -> None:
    """Admin pages retain the requested generic feature names and table structure."""
    expected = {
        "users.html": "Users",
        "logins.html": "Logins",
        "prompt_runs.html": "Prompt Runs",
        "chat_feedback.html": "Chat Feedback",
        "model_usage.html": "Model Usage",
        "exceptions.html": "Exceptions",
        "knowledge.html": "Knowledge",
        "tool_use.html": "Tool Use",
    }
    forbidden = re.compile(
        r"salesforce|myclubhub|bgcmd|school harbor|organizational "
        r"knowledge",
        re.I,
    )

    for filename, heading in expected.items():
        markup = _template(filename)
        assert f"<h1>{heading}</h1>" in markup
        assert "<table" in markup or filename == "knowledge.html"
        assert not forbidden.search(markup), filename


def test_approved_palette_has_visible_focus_and_reduced_motion_rules() -> None:
    """The calm palette remains keyboard-visible and respects reduced-motion preferences."""
    stylesheet = ROOT / "src" / "project_recovery" / "static" / "app.css"
    css = stylesheet.read_text(encoding="utf-8")

    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "--" in css
    assert "#" in css
