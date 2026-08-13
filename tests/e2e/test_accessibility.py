"""Static accessibility and generic-product contract checks for rendered pages."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "project_recovery" / "templates"


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


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
