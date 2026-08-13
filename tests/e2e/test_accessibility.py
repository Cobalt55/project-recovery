"""Static accessibility and generic-product contract checks for rendered pages."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader

from project_recovery.admin.logins import login_status

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


def _render_logins_page() -> str:
    """Render the real session view with controlled safe projection values."""
    now = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)
    return (
        Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
        .get_template("logins.html")
        .render(
            user=SimpleNamespace(email="admin@example.test", force_password_change=False),
            csrf_token="test-csrf",
            navigation=[],
            logins=[
                SimpleNamespace(
                    id=uuid4(),
                    email="member@example.test",
                    is_active=True,
                    created_at=now,
                    last_seen_at=now + timedelta(minutes=5),
                    expires_at=now + timedelta(hours=12),
                    revoked_at=None,
                )
            ],
            login_status=login_status,
            offset=0,
            limit=25,
            query="",
            status="all",
            has_next=False,
            previous_offset=None,
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


@pytest.fixture
def logins_page() -> Page:
    """Load the rendered login session page with its shipped responsive assets."""
    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1024, "height": 720})
        page.set_content(_render_logins_page())
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


def test_login_sessions_switch_to_stacked_rows_on_mobile_without_overflow(
    logins_page: Page,
) -> None:
    """Leaving the desktop table visible on phones makes session administration unusable."""
    assert logins_page.locator(".session-table").is_visible()
    assert logins_page.locator(".session-list").is_hidden()

    logins_page.set_viewport_size({"width": 390, "height": 720})

    assert logins_page.locator(".session-table").is_hidden()
    assert logins_page.locator(".session-list").is_visible()
    assert logins_page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_login_revoke_prompts_for_confirmation(logins_page: Page) -> None:
    """A direct revoke submission can invalidate a live session without deliberate confirmation."""
    confirmations: list[str] = []

    def dismiss(dialog: object) -> None:
        confirmations.append(dialog.message)
        dialog.dismiss()

    logins_page.once("dialog", dismiss)
    logins_page.get_by_text("Session details").first.click()
    logins_page.get_by_role("button", name="Revoke").click()

    assert confirmations == ["Revoke this session?"]


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


def test_chainlit_shim_covers_native_controls_and_reduces_history_to_one_tab_stop() -> None:
    """The Chainlit enhancement must provide names without replacing native controls."""

    navigation = (ROOT / "public" / "chat-navigation.js").read_text(encoding="utf-8")

    for control in (
        "#sidebar-trigger-button",
        "#search-chats-button",
        "#new-chat-button",
        "Sidebar",
        "Search conversations",
        "New chat",
        "Attach files",
        "Chat settings",
        "Send message",
        "Account menu",
    ):
        assert control in navigation
    assert 'tabindex", "-1"' in navigation
    assert 'aria-hidden", "true"' in navigation
    assert "role=dialog" in navigation
    assert "aria-describedby" in navigation
    assert "data-pr-submitting" in navigation
    assert "data-pr-drawer-open" in navigation
    assert "data-pr-drawer-close" in navigation


def test_chainlit_workspace_shim_targets_current_native_icon_control_ids() -> None:
    """A Chainlit ID drift must not silently reintroduce unnamed Chat icon controls."""
    navigation = (ROOT / "public" / "chat-navigation.js").read_text(encoding="utf-8")

    for selector in (
        "#sidebar-trigger-button",
        "#search-chats-button",
        "#new-chat-button",
        "#user-nav-button",
    ):
        assert selector in navigation


def test_chainlit_workspace_shim_behaves_safely_for_native_and_dynamic_controls() -> None:
    """The shipped shim must preserve native actions while improving their browser behavior."""

    navigation = (ROOT / "public" / "chat-navigation.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "public" / "chat-navigation.css").read_text(encoding="utf-8")
    markup = """
    <button id="sidebar-open"></button>
    <button id="sidebar-close"></button>
    <input id="thread-search">
    <button id="new-chat"></button>
    <button id="upload-button"></button>
    <button id="chat-submit"></button>
    <button id="stop-button"></button>
    <button data-testid="user-menu"></button>
    <a href="/thread/duplicate" aria-label="Thread duplicate">
      <button aria-label="Thread duplicate">Open</button>
    </a>
    <a href="/thread/options" aria-label="Thread options">
      <button aria-label="Thread options menu">Options</button>
    </a>
    <article id="message">Chainlit</article>
    """

    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 720})
        page.set_content(markup)
        page.add_style_tag(content=stylesheet)
        page.evaluate(
            """window.fetch = async () => ({
                ok: true,
                json: async () => ({ items: [
                    { label: 'Chat', href: '/chat', active: true },
                    { label: 'Settings', href: '/settings', active: false },
                ] }),
            })"""
        )
        page.locator("#chat-submit").evaluate(
            """element => {
                window.submitEvents = 0;
                element.addEventListener('click', () => window.submitEvents += 1);
            }"""
        )
        page.add_script_tag(content=navigation)
        page.locator("#project-recovery-nav").wait_for()

        nav = page.locator("#project-recovery-nav")
        toggle = page.locator("#project-recovery-nav-toggle")
        backdrop = page.locator("#project-recovery-nav-backdrop")
        assert nav.get_attribute("aria-hidden") == "true"
        assert nav.get_attribute("inert") is not None
        assert backdrop.is_hidden()
        assert not page.locator("#project-recovery-nav a").first.evaluate(
            "element => { element.focus(); return document.activeElement === element; }"
        )

        for selector in (
            "#sidebar-open",
            "#sidebar-close",
            "#thread-search",
            "#new-chat",
            "#upload-button",
            "#chat-submit",
            "#stop-button",
            "[data-testid='user-menu']",
        ):
            for property_name in ("minHeight", "minWidth"):
                assert (
                    page.locator(selector).evaluate(
                        f"element => Number.parseFloat(getComputedStyle(element).{property_name})"
                    )
                    >= 44
                )

        page.evaluate(
            """document.body.insertAdjacentHTML(
                'beforeend', '<button id="chat-settings-open-modal"></button>'
            )"""
        )
        assert (
            page.locator("#chat-settings-open-modal").get_attribute("aria-label") == "Chat settings"
        )
        for property_name in ("minHeight", "minWidth"):
            assert (
                page.locator("#chat-settings-open-modal").evaluate(
                    f"element => Number.parseFloat(getComputedStyle(element).{property_name})"
                )
                >= 44
            )

        page.locator("#upload-button").evaluate(
            """element => {
                element.removeAttribute('aria-label');
                element.setAttribute('role', 'presentation');
            }"""
        )
        page.wait_for_function(
            """() => {
                const upload = document.querySelector('#upload-button');
                return upload?.getAttribute('aria-label') === 'Attach files';
            }"""
        )
        assert page.locator("#upload-button").get_attribute("role") is None

        stop_result = page.locator("#stop-button").evaluate(
            """async (element) => {
                let mutations = 0;
                const observer = new MutationObserver((records) => {
                    mutations += records.length;
                });
                observer.observe(element, { attributes: true, attributeFilter: ['aria-label'] });
                window.stopLabelTimerCompleted = false;
                window.setTimeout(() => { window.stopLabelTimerCompleted = true; }, 0);
                element.setAttribute('aria-label', 'Send message');
                await new Promise((resolve) => window.setTimeout(resolve, 25));
                observer.disconnect();
                return {
                    mutations,
                    label: element.getAttribute('aria-label'),
                    timerCompleted: window.stopLabelTimerCompleted,
                };
            }"""
        )
        assert stop_result == {
            "mutations": 2,
            "label": "Stop response",
            "timerCompleted": True,
        }

        submit = page.locator("#chat-submit")
        submit.click()
        submit.click()
        assert page.evaluate("window.submitEvents") == 1

        assert page.locator("a[href='/thread/duplicate'] button").get_attribute("tabindex") == "-1"
        assert page.locator("a[href='/thread/options'] button").get_attribute("tabindex") is None
        assert page.locator("#message").inner_text() == "Chainlit"

        toggle.click()
        assert nav.get_attribute("aria-hidden") == "false"
        assert nav.get_attribute("inert") is None
        assert not backdrop.is_hidden()
        first_control = nav.locator("[data-pr-drawer-close]")
        last_link = nav.locator("a").last
        last_link.focus()
        page.keyboard.press("Tab")
        assert first_control.evaluate("element => document.activeElement === element")
        first_control.focus()
        page.keyboard.press("Shift+Tab")
        assert last_link.evaluate("element => document.activeElement === element")
        page.keyboard.press("Escape")
        assert nav.get_attribute("aria-hidden") == "true"
        assert toggle.evaluate("element => document.activeElement === element")

        toggle.click()
        page.mouse.click(350, 300)
        assert nav.get_attribute("aria-hidden") == "true"
        assert toggle.evaluate("element => document.activeElement === element")

        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', '<button id=\"main-after\"></button>')"
        )
        page.set_viewport_size({"width": 1024, "height": 720})
        page.wait_for_function(
            """() => {
                const nav = document.querySelector('#project-recovery-nav');
                return nav?.getAttribute('aria-hidden') === 'false' && !nav?.hasAttribute('inert');
            }"""
        )
        last_link.focus()
        page.keyboard.press("Tab")
        assert page.locator("#chat-settings-open-modal").evaluate(
            "element => document.activeElement === element"
        )
        page.keyboard.press("Tab")
        assert page.locator("#main-after").evaluate("element => document.activeElement === element")
        browser.close()


def test_chainlit_submit_guard_blocks_a_replaced_stop_only_during_transition() -> None:
    """A second rapid activation must not turn a just-sent message into cancellation."""

    navigation = (ROOT / "public" / "chat-navigation.js").read_text(encoding="utf-8")
    markup = '<button id="chat-submit" type="button">Send</button>'

    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(markup)
        page.evaluate(
            """() => {
                window.fetch = async () => ({ ok: true, json: async () => ({ items: [] }) });
                window.sendEvents = 0;
                window.stopEvents = 0;
                document.querySelector('#chat-submit').addEventListener('click', (event) => {
                  if (event.defaultPrevented) return;
                  window.sendEvents += 1;
                  event.currentTarget.outerHTML = [
                    '<button id="stop-button" type="button">Stop</button>',
                  ].join('');
                  document.querySelector('#stop-button').addEventListener('click', (stopEvent) => {
                    if (!stopEvent.defaultPrevented) window.stopEvents += 1;
                  });
                });
            }"""
        )
        page.add_script_tag(content=navigation)

        page.locator("#chat-submit").click()
        page.locator("#stop-button").click()
        assert page.evaluate("window.sendEvents") == 1
        assert page.evaluate("window.stopEvents") == 0

        page.wait_for_timeout(950)
        page.locator("#stop-button").click()
        assert page.evaluate("window.stopEvents") == 1
        browser.close()


def test_admin_activity_script_localizes_marked_time_without_losing_exact_value() -> None:
    """Removing client localization must expose the fixed server UTC label again."""

    script = (STATIC / "app.js").read_text(encoding="utf-8")
    exact = "2026-08-12T00:00:00+00:00"
    markup = (
        f'<time data-local-time datetime="{exact}" title="{exact}">Aug 12, 2026 00:00 UTC</time>'
    )

    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", timezone_id="America/New_York")
        page = context.new_page()
        page.set_content(markup)
        page.add_script_tag(content=script)

        timestamp = page.locator("time")
        assert timestamp.inner_text() == "Aug 11, 2026, 8:00 PM"
        assert timestamp.get_attribute("datetime") == exact
        assert timestamp.get_attribute("title") == exact
        browser.close()


def test_admin_copy_status_reannounces_identical_success_messages() -> None:
    """Two successful copy actions must produce two distinct polite announcements."""

    script = (STATIC / "app.js").read_text(encoding="utf-8")
    markup = '<button type="button" data-copy-value="record-1">Copy</button>'

    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(markup)
        page.evaluate(
            """() => {
                Object.defineProperty(navigator, 'clipboard', {
                  configurable: true,
                  value: { writeText: async () => undefined },
                });
                window.pendingAnnouncementFrame = null;
                window.requestAnimationFrame = (callback) => {
                  window.pendingAnnouncementFrame = callback;
                  return 1;
                };
            }"""
        )
        page.add_script_tag(content=script)
        button = page.locator("[data-copy-value]")
        status = page.get_by_role("status")

        button.click()
        page.wait_for_function("() => window.pendingAnnouncementFrame !== null")
        assert status.inner_text() == ""
        page.evaluate(
            """() => {
                const callback = window.pendingAnnouncementFrame;
                window.pendingAnnouncementFrame = null;
                callback();
            }"""
        )
        assert status.inner_text() == "Copied to clipboard."

        button.click()
        page.wait_for_function("() => window.pendingAnnouncementFrame !== null")
        assert status.inner_text() == ""
        page.evaluate("() => window.pendingAnnouncementFrame()")
        assert status.inner_text() == "Copied to clipboard."
        browser.close()
