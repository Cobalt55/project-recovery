"""FastAPI application factory for the authenticated workspace shell."""

import logging
import os
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from chainlit.auth import create_jwt
from chainlit.user import User as ChainlitUser
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from project_recovery.admin.exceptions import exception_rows
from project_recovery.admin.feedback import feedback_rows
from project_recovery.admin.logins import login_status
from project_recovery.admin.model_usage import USAGE_WINDOWS, usage_view, window_start
from project_recovery.admin.prompt_runs import prompt_run_rows
from project_recovery.admin.settings import validated_settings
from project_recovery.admin.shell import AppServices, navigation_items
from project_recovery.admin.tool_use import tool_run_rows
from project_recovery.admin.users import UserManagementService
from project_recovery.agent_runtime import AgentRuntime
from project_recovery.auth.passwords import PasswordService
from project_recovery.auth.rate_limit import LoginRateLimiter
from project_recovery.auth.sessions import AuthService, CurrentUser
from project_recovery.chat_state import ChatDependencies, configure_chat
from project_recovery.config import (
    Settings,
    get_settings,
)
from project_recovery.db import Database
from project_recovery.knowledge.routes import KNOWLEDGE_STATUSES, knowledge_rows
from project_recovery.knowledge.service import KnowledgeService, KnowledgeValidationError
from project_recovery.repositories.chat import ChatRepository
from project_recovery.repositories.knowledge import KnowledgeRepository
from project_recovery.repositories.telemetry import TelemetryRepository
from project_recovery.repositories.users import UserRepository

LOGGER = logging.getLogger(__name__)
PACKAGE_ROOT = Path(__file__).parent
SESSION_COOKIE = "project_recovery_session"
CSRF_COOKIE = "project_recovery_csrf"
CHAINLIT_COOKIE_PREFIX = "access_token"


def _services(settings: Settings) -> AppServices:
    database = Database(settings.database_url)
    passwords = PasswordService()
    sessions = database.session()
    auth = AuthService(sessions, passwords)
    users = UserRepository(sessions)
    chats = ChatRepository(sessions)
    telemetry = TelemetryRepository(sessions)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    knowledge_repository = KnowledgeRepository(sessions)
    knowledge = KnowledgeService(
        repository=knowledge_repository,
        openai_client=openai_client,
        vector_store_id=settings.openai_vector_store_id,
        staging_root=Path(settings.attachment_storage_path) / "knowledge",
    )
    return AppServices(
        database=database,
        auth=auth,
        users=UserManagementService(database, passwords),
        chat=ChatDependencies(
            auth=auth,
            users=users,
            chats=chats,
            runtime=AgentRuntime(
                settings=settings,
                chat_repository=chats,
                telemetry_repository=telemetry,
                openai_client=openai_client,
            ),
            attachment_root=Path(settings.attachment_storage_path),
        ),
        telemetry=telemetry,
        chats=chats,
        knowledge=knowledge,
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
    response: Response,
    session_token: str,
    csrf_token: str,
    current: CurrentUser,
    settings: Settings,
) -> None:
    secure = settings.environment.casefold() == "production"
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, samesite="lax", secure=secure, path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, samesite="lax", secure=secure, path="/"
    )
    response.set_cookie(
        CHAINLIT_COOKIE_PREFIX,
        create_jwt(
            ChainlitUser(
                identifier=str(current.user_id),
                display_name=current.email,
                metadata={"roles": list(current.roles)},
            )
        ),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=12 * 60 * 60,
    )


def _clear_login_cookies(response: Response, request: Request) -> None:
    """Clear application and mounted-Chainlit credentials together."""
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    for name in request.cookies:
        if name == CHAINLIT_COOKIE_PREFIX or name.startswith(f"{CHAINLIT_COOKIE_PREFIX}_"):
            response.delete_cookie(name, path="/")


def create_app(settings: Settings | None = None, services: AppServices | None = None) -> FastAPI:
    """Build the production-safe workspace and its authenticated chat."""
    configured = settings or get_settings()
    application_services = services or _services(configured)
    templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
    login_limiter = LoginRateLimiter()
    os.environ["CHAINLIT_AUTH_SECRET"] = configured.chainlit_auth_secret.get_secret_value()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if application_services.knowledge is not None:
            try:
                await application_services.knowledge.recover_stale()
            except Exception:
                LOGGER.error("Knowledge startup recovery could not complete.")
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
        except Exception as error:
            if application_services.telemetry is not None:
                api_key = configured.openai_api_key.get_secret_value()
                message = str(error)
                stack = traceback.format_exc()
                if api_key:
                    message = message.replace(api_key, "[REDACTED]")
                    stack = stack.replace(api_key, "[REDACTED]")
                actor_id = None
                try:
                    actor = await application_services.auth.current_user(
                        request.cookies.get(SESSION_COOKIE, "")
                    )
                    actor_id = actor.user_id if actor is not None else None
                except Exception:
                    pass
                try:
                    await application_services.telemetry.record_exception(
                        request_path=request.url.path,
                        user_id=actor_id,
                        exception_type=type(error).__name__,
                        message=message,
                        stack_trace=stack,
                        context={
                            "correlation_id": correlation_id,
                            "method": request.method,
                        },
                    )
                except Exception:
                    pass
            LOGGER.error(
                "request failed correlation_id=%s path=%s", correlation_id, request.url.path
            )
            raise
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["Cache-Control"] = "no-store"
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

    @app.get("/api/navigation")
    async def navigation(request: Request) -> Response:
        current = await _current_user(request, application_services)
        if not isinstance(current, CurrentUser):
            return JSONResponse({"items": []}, status_code=401)
        return JSONResponse(
            {
                "items": [
                    {"label": item.label, "href": item.href}
                    for item in navigation_items(current, request.url.path)
                ]
            }
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request) -> Response:
        current = await _current_user(request, application_services)
        if isinstance(current, CurrentUser):
            return _redirect("/chat")
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login(
        request: Request, email: Annotated[str, Form()], password: Annotated[str, Form()]
    ) -> Response:
        client_address = request.client.host if request.client is not None else "unknown"
        if not await login_limiter.is_allowed(client_address, email):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "We could not sign you in with those details."},
                status_code=429,
                headers={"Retry-After": "900"},
            )
        result = await application_services.auth.login(email, password)
        if result is None:
            await login_limiter.record_failure(client_address, email)
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "We could not sign you in with those details."},
                status_code=401,
            )
        await login_limiter.record_success(client_address, email)
        current = await application_services.auth.current_user(result.session_token)
        if current is None:
            await application_services.auth.logout(result.session_token)
            return Response(status_code=401)
        response = _redirect("/password/change" if current.force_password_change else "/chat")
        _set_login_cookies(
            response,
            result.session_token,
            result.csrf_token,
            current,
            configured,
        )
        return response

    @app.post("/logout")
    async def logout(
        request: Request, csrf_token: Annotated[str | None, Form()] = None
    ) -> Response:
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        await application_services.auth.logout(request.cookies.get(SESSION_COOKIE, ""))
        response = _redirect("/login")
        _clear_login_cookies(response, request)
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
        _clear_login_cookies(response, request)
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
            return Response("Unable to update this user.", status_code=400)
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

    @app.post("/admin/logins/{login_id}/revoke")
    async def revoke_login(
        request: Request, login_id: UUID, csrf_token: Annotated[str | None, Form()] = None
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        await application_services.users.revoke_login(current.user_id, login_id)
        return _redirect("/admin/logins")

    @app.get("/admin/prompt-runs", response_class=HTMLResponse)
    async def prompt_runs_page(request: Request, offset: int = 0, limit: int = 50) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.telemetry is None:
            return Response(status_code=503)
        page_size = min(max(limit, 1), 50)
        records = list(
            await application_services.telemetry.list_prompt_runs(max(offset, 0), page_size + 1)
        )
        return templates.TemplateResponse(
            request,
            "prompt_runs.html",
            _page_context(
                request,
                current,
                rows=prompt_run_rows(records[:page_size]),
                has_next=len(records) > page_size,
                next_offset=max(offset, 0) + page_size,
                limit=page_size,
            ),
        )

    @app.get("/admin/chat-feedback", response_class=HTMLResponse)
    async def chat_feedback_page(request: Request, offset: int = 0, limit: int = 50) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.chats is None:
            return Response(status_code=503)
        page_size = min(max(limit, 1), 50)
        records = list(
            await application_services.chats.list_feedback(max(offset, 0), page_size + 1)
        )
        return templates.TemplateResponse(
            request,
            "chat_feedback.html",
            _page_context(
                request,
                current,
                rows=feedback_rows(records[:page_size]),
                has_next=len(records) > page_size,
                next_offset=max(offset, 0) + page_size,
                limit=page_size,
            ),
        )

    @app.get("/admin/model-usage", response_class=HTMLResponse)
    async def model_usage_page(request: Request, window: str = "30d") -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.telemetry is None:
            return Response(status_code=503)
        try:
            since = window_start(window)
        except ValueError:
            return Response("Unsupported usage window.", status_code=400)
        summary = await application_services.telemetry.usage_summary(since)
        return templates.TemplateResponse(
            request,
            "model_usage.html",
            _page_context(
                request,
                current,
                usage=usage_view(summary),
                windows=tuple(USAGE_WINDOWS),
                window=window,
            ),
        )

    @app.get("/admin/exceptions", response_class=HTMLResponse)
    async def exceptions_page(request: Request, offset: int = 0, limit: int = 50) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.telemetry is None:
            return Response(status_code=503)
        page_size = min(max(limit, 1), 50)
        records = list(
            await application_services.telemetry.list_exceptions(max(offset, 0), page_size + 1)
        )
        return templates.TemplateResponse(
            request,
            "exceptions.html",
            _page_context(
                request,
                current,
                rows=exception_rows(records[:page_size]),
                has_next=len(records) > page_size,
                next_offset=max(offset, 0) + page_size,
                limit=page_size,
            ),
        )

    @app.get("/admin/tool-use", response_class=HTMLResponse)
    async def tool_use_page(request: Request, offset: int = 0, limit: int = 50) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.telemetry is None:
            return Response(status_code=503)
        page_size = min(max(limit, 1), 50)
        records = list(
            await application_services.telemetry.list_tool_runs(max(offset, 0), page_size + 1)
        )
        return templates.TemplateResponse(
            request,
            "tool_use.html",
            _page_context(
                request,
                current,
                rows=tool_run_rows(records[:page_size]),
                has_next=len(records) > page_size,
                next_offset=max(offset, 0) + page_size,
                limit=page_size,
            ),
        )

    @app.get("/admin/knowledge", response_class=HTMLResponse)
    async def knowledge_page(
        request: Request,
        query: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.knowledge is None:
            return Response(status_code=503)
        if status and status not in KNOWLEDGE_STATUSES:
            return Response("Unsupported status.", status_code=400)
        page_size = min(max(limit, 1), 50)
        records = list(
            await application_services.knowledge.list_page(
                query=query,
                status=status,
                offset=max(offset, 0),
                limit=page_size + 1,
            )
        )
        return templates.TemplateResponse(
            request,
            "knowledge.html",
            _page_context(
                request,
                current,
                rows=knowledge_rows(records[:page_size]),
                statuses=KNOWLEDGE_STATUSES,
                query=query or "",
                selected_status=status or "",
                has_next=len(records) > page_size,
                next_offset=max(offset, 0) + page_size,
                limit=page_size,
            ),
        )

    @app.get("/admin/knowledge/status")
    async def knowledge_status(request: Request) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if application_services.knowledge is None:
            return Response(status_code=503)
        records = await application_services.knowledge.list_page(
            query=None, status=None, offset=0, limit=100
        )
        return JSONResponse(
            {
                "items": [
                    {"id": str(row.id), "status": row.status, "error": row.error_message}
                    for row in records
                ]
            }
        )

    @app.post("/admin/knowledge")
    async def knowledge_upload(
        request: Request,
        background: BackgroundTasks,
        csrf_token: Annotated[str | None, Form()] = None,
        category: Annotated[str | None, Form()] = None,
        description: Annotated[str | None, Form()] = None,
        upload: UploadFile = File(...),
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        if application_services.knowledge is None:
            return Response(status_code=503)
        content = await upload.read(25 * 1024 * 1024 + 1)
        try:
            resource = await application_services.knowledge.queue_upload(
                filename=upload.filename or "",
                content=content,
                category=category,
                description=description,
            )
        except KnowledgeValidationError as error:
            return Response(str(error), status_code=400)
        background.add_task(application_services.knowledge.ingest, resource.id)
        return JSONResponse({"id": str(resource.id), "status": "queued"}, status_code=202)

    @app.post("/admin/knowledge/{resource_id}/retry")
    async def knowledge_retry(
        request: Request,
        background: BackgroundTasks,
        resource_id: UUID,
        csrf_token: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        if application_services.knowledge is None:
            return Response(status_code=503)
        if not await application_services.knowledge.retry(resource_id):
            return Response(status_code=409)
        background.add_task(application_services.knowledge.ingest, resource_id)
        return _redirect("/admin/knowledge")

    @app.post("/admin/knowledge/{resource_id}/delete")
    async def knowledge_delete(
        request: Request,
        resource_id: UUID,
        csrf_token: Annotated[str | None, Form()] = None,
        confirm: Annotated[str | None, Form()] = None,
    ) -> Response:
        current = await admin(request)
        if not isinstance(current, CurrentUser):
            return current
        if not await _csrf_valid(request, application_services, csrf_token or ""):
            return Response(status_code=403)
        if confirm != "delete":
            return Response("Deletion confirmation is required.", status_code=400)
        if application_services.knowledge is None:
            return Response(status_code=503)
        if not await application_services.knowledge.delete(resource_id):
            return Response(status_code=409)
        return _redirect("/admin/knowledge")

    if application_services.chat is not None:
        from chainlit.utils import mount_chainlit

        configure_chat(application_services.chat)
        mount_chainlit(
            app=app,
            target=str(PACKAGE_ROOT / "chat_app.py"),
            path="/chat",
        )

    return app


__all__ = ["create_app"]
