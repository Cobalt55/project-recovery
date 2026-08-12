"""FastAPI application factory for the authenticated workspace shell."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from project_recovery.admin.logins import login_status
from project_recovery.admin.settings import validated_settings
from project_recovery.admin.shell import AppServices, navigation_items
from project_recovery.admin.users import UserManagementService
from project_recovery.auth.passwords import PasswordService
from project_recovery.auth.sessions import AuthService, CurrentUser
from project_recovery.config import (
    Settings,
    get_settings,
)
from project_recovery.db import Database

LOGGER = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).parent
SESSION_COOKIE = "project_recovery_session"
CSRF_COOKIE = "project_recovery_csrf"


def _services(settings: Settings) -> AppServices:
    database = Database(settings.database_url)
    passwords = PasswordService()
    return AppServices(
        database=database,
        auth=AuthService(database.session(), passwords),
        users=UserManagementService(database, passwords),
    )


def _page_context(request: Request, user: CurrentUser, **context: object) -> dict[str, object]:
    """Supply every authenticated template with stable shell state."""
    return {
        "user": user,
        "navigation": navigation_items(user, request.url.path),
        "csrf_token": request.cookies.get(CSRF_COOKIE, ""),
        **context,
    }


def _redirect(location: str) -> RedirectResponse:
    return RedirectResponse(location, status_code=303)


async def _current_user(
    request: Request, services: AppServices, *, allow_password_change: bool = False
) -> CurrentUser | RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE, "")
    user = await services.auth.current_user(token)
    if user is None:
        return _redirect("/login")
    if user.force_password_change and not allow_password_change:
        return _redirect("/password/change")
    return user


async def _csrf_valid(request: Request, services: AppServices, csrf_token: str) -> bool:
    return await services.auth.validate_csrf(request.cookies.get(SESSION_COOKIE, ""), csrf_token)


def _set_login_cookies(
    response: Response, session_token: str, csrf_token: str, settings: Settings
) -> None:
    secure = settings.environment.casefold() == "production"
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, samesite="lax", secure=secure, path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, samesite="lax", secure=secure, path="/"
    )


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    """Build the production-safe web application without mounting the chat runtime yet."""
    configured = settings or get_settings()
    application_services = services or _services(configured)
    templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await application_services.database.close()

    app = FastAPI(title=configured.app_name, debug=False, lifespan=lifespan)
    app.state.services = application_services
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(configured.trusted_hosts))
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")

    @app.middleware("http")
    async def sanitize_unhandled_exceptions(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = uuid4().hex
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception:
            # Starlette produces the safe response; logs retain no exception text.
            LOGGER.error(
                "request failed correlation_id=%s path=%s", correlation_id, request.url.path
            )
            raise
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.get("/health/live")
    async def live(request: Request) -> JSONResponse:
        return JSONResponse({"application": True, "correlation_id": request.state.correlation_id})

    @app.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "database": await application_services.database.ping(),
                "application": True,
                "correlation_id": request.state.correlation_id,
            }
        )

    @app.get("/")
    async def root() -> RedirectResponse:
        return _redirect("/chat")

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> Response:
        current = await _current_user(request, application_services)
        if isinstance(current, CurrentUser):
            return _redirect("/settings")
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login(
        request: Request, email: Annotated[str, Form()], password: Annotated[str, Form()]
    ) -> Response:
        result = await application_services.auth.login(email, password)
        if result is None:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "We could not sign you in with those details."},
                status_code=401,
            )
        current = await application_services.auth.current_user(result.session_token)
        response = _redirect(
            "/password/change" if current and current.force_password_change else "/settings"
        )
        _set_login_cookies(response, result.session_token, result.csrf_token, configured)
        return response

    @app.post("/logout")
    async def logout(
        request: Request, csrf_token: Annotated[str | None, Form()] = None
    ) -> Response:
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        await application_services.auth.logout(request.cookies.get(SESSION_COOKIE, ""))
        response = _redirect("/login")
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return response

    @app.get("/password/change", response_class=HTMLResponse)
    async def password_change_form(request: Request) -> Response:
        current = await _current_user(request, application_services, allow_password_change=True)
        if isinstance(current, RedirectResponse):
            return current
        return templates.TemplateResponse(
            request,
            "settings.html",
            _page_context(request, current, password_only=True, settings={}),
        )

    @app.post("/password/change")
    async def password_change(
        request: Request,
        csrf_token: Annotated[str | None, Form()] = None,
        current_password: Annotated[str | None, Form()] = None,
        new_password: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await _current_user(request, application_services, allow_password_change=True)
        if isinstance(current, RedirectResponse):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        if not await application_services.auth.change_password(
            request.cookies.get(SESSION_COOKIE, ""), current_password or "", new_password or ""
        ):
            return Response("Unable to update your password.", status_code=400)
        response = _redirect("/login")
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return response

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> Response:
        current = await _current_user(request, application_services)
        if isinstance(current, RedirectResponse):
            return current
        values = await application_services.users.get_settings(current.user_id)
        return templates.TemplateResponse(
            request,
            "settings.html",
            _page_context(request, current, settings=values, password_only=False),
        )

    @app.post("/settings")
    async def save_settings(
        request: Request,
        csrf_token: Annotated[str | None, Form()] = None,
        model: Annotated[str | None, Form()] = None,
        reasoning_effort: Annotated[str | None, Form()] = None,
        theme: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await _current_user(request, application_services)
        if isinstance(current, RedirectResponse):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        values = validated_settings(model or "", reasoning_effort or "", theme or "")
        if values is None:
            return Response("Invalid settings.", status_code=400)
        await application_services.users.save_settings(current.user_id, values)
        return _redirect("/settings")

    async def admin(request: Request) -> CurrentUser | Response:
        current = await _current_user(request, application_services)
        if isinstance(current, RedirectResponse):
            return current
        return current if current.is_admin else Response(status_code=403)

    @app.get("/admin/users", response_class=HTMLResponse)
    async def users_page(
        request: Request,
        query: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        rows = await application_services.users.list_page(
            query, status, max(offset, 0), min(max(limit, 1), 100)
        )
        return templates.TemplateResponse(
            request,
            "users.html",
            _page_context(request, current, users=rows, temporary_password=None),
        )

    @app.post("/admin/users", response_class=HTMLResponse)
    async def create_user(
        request: Request,
        csrf_token: Annotated[str | None, Form()] = None,
        email: Annotated[str | None, Form()] = None,
        display_name: Annotated[str | None, Form()] = None,
        roles: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        try:
            temporary_password = await application_services.users.create_user(
                current.user_id, email or "", display_name or "", (roles or "").split(",")
            )
        except ValueError:
            return Response("Unable to create this user.", status_code=400)
        rows = await application_services.users.list_page(None, None, 0, 25)
        return templates.TemplateResponse(
            request,
            "users.html",
            _page_context(request, current, users=rows, temporary_password=temporary_password),
        )

    @app.post("/admin/users/{user_id}/active")
    async def update_active(
        request: Request,
        user_id: UUID,
        csrf_token: Annotated[str | None, Form()] = None,
        is_active: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        try:
            await application_services.users.set_active(
                current.user_id, user_id, is_active == "true"
            )
        except ValueError:
            return Response(status_code=404)
        return _redirect("/admin/users")

    @app.post("/admin/users/{user_id}/roles")
    async def update_roles(
        request: Request,
        user_id: UUID,
        csrf_token: Annotated[str | None, Form()] = None,
        roles: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        try:
            await application_services.users.set_roles(
                current.user_id, user_id, (roles or "").split(",")
            )
        except ValueError:
            return Response(status_code=400)
        return _redirect("/admin/users")

    @app.post("/admin/users/{user_id}/reset", response_class=HTMLResponse)
    async def reset_password(
        request: Request, user_id: UUID, csrf_token: Annotated[str | None, Form()] = None
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        try:
            temporary_password = await application_services.users.reset_password(
                current.user_id, user_id
            )
        except ValueError:
            return Response(status_code=404)
        rows = await application_services.users.list_page(None, None, 0, 25)
        return templates.TemplateResponse(
            request,
            "users.html",
            _page_context(request, current, users=rows, temporary_password=temporary_password),
        )

    @app.get("/admin/logins", response_class=HTMLResponse)
    async def logins_page(request: Request, offset: int = 0, limit: int = 25) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        logins = await application_services.users.list_logins(
            max(offset, 0), min(max(limit, 1), 100)
        )
        return templates.TemplateResponse(
            request,
            "logins.html",
            _page_context(request, current, logins=logins, login_status=login_status),
        )

    return app


__all__ = ["create_app"]
