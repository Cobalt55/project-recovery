"""Optional release smoke tests against a running local or deployed application.

Set ``E2E_BASE_URL``, ``E2E_EMAIL``, and ``E2E_PASSWORD`` to enable this module.
The tests intentionally skip without those variables so ordinary unit and
integration runs never need a live server or credentials.
"""

import os
import re
from collections.abc import Iterator

import httpx
import pytest

ADMIN_ROUTES = (
    "/admin/users",
    "/admin/logins",
    "/admin/prompt-runs",
    "/admin/chat-feedback",
    "/admin/model-usage",
    "/admin/exceptions",
    "/admin/knowledge",
    "/admin/tool-use",
)
CSRF_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _required_environment() -> tuple[str, str, str]:
    base_url = os.environ.get("E2E_BASE_URL")
    email = os.environ.get("E2E_EMAIL")
    password = os.environ.get("E2E_PASSWORD")
    if not base_url or not email or not password:
        pytest.skip("set E2E_BASE_URL, E2E_EMAIL, and E2E_PASSWORD for live smoke tests")
    return base_url.rstrip("/"), email, password


@pytest.fixture
def live_client() -> Iterator[httpx.Client]:
    base_url, _, _ = _required_environment()
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=20.0) as client:
        yield client


def _csrf(page: httpx.Response) -> str:
    match = CSRF_PATTERN.search(page.text)
    assert match is not None, "authenticated page did not expose a CSRF form token"
    return match.group(1)


def test_login_settings_chat_and_all_admin_pages_are_reachable(
    live_client: httpx.Client,
) -> None:
    """A configured account can sign in and reach every approved workspace destination."""
    _, email, password = _required_environment()
    login_page = live_client.get("/login")
    assert login_page.status_code == 200
    assert "Sign in" in login_page.text

    login = live_client.post("/login", data={"email": email, "password": password})
    assert login.status_code in {302, 303}
    assert login.headers["location"] in {"/settings", "/chat", "/password/change"}
    if login.headers["location"] == "/password/change":
        pytest.skip("configured account still requires its one-time password change")

    settings = live_client.get("/settings")
    chat = live_client.get("/chat")
    assert settings.status_code == 200
    assert chat.status_code == 200
    assert all(
        option in settings.text for option in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol")
    )
    assert all(option in settings.text for option in ("low", "medium", "high"))

    settings_save = live_client.post(
        "/settings",
        data={
            "csrf_token": _csrf(settings),
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "theme": "system",
        },
    )
    assert settings_save.status_code in {302, 303}

    for route in ADMIN_ROUTES:
        response = live_client.get(route)
        assert response.status_code == 200, route


def test_invalid_settings_are_rejected_without_a_server_error(live_client: httpx.Client) -> None:
    """A signed-in browser cannot persist an unsupported model or reasoning setting."""
    _, email, password = _required_environment()
    login = live_client.post("/login", data={"email": email, "password": password})
    if login.headers.get("location") == "/password/change":
        pytest.skip("configured account still requires its one-time password change")
    settings = live_client.get("/settings")
    assert settings.status_code == 200

    invalid = live_client.post(
        "/settings",
        data={
            "csrf_token": _csrf(settings),
            "model": "gpt-secret-model",
            "reasoning_effort": "extreme",
            "theme": "system",
        },
    )
    assert invalid.status_code == 400
    assert "gpt-secret-model" not in invalid.text
    assert "OPENAI_API_KEY" not in invalid.text
