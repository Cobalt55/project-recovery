# Project Recovery Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, deploy, and verify a generic Chainlit chatbot with durable OpenAI Conversations, PostgreSQL-backed history and administration, deeply integrated Agents SDK tracing, shared vector-store knowledge, and the approved functional pages.

**Architecture:** A modular FastAPI monolith mounts Chainlit at `/chat`, serves the administrator workspace, and shares typed services and repositories. PostgreSQL is the application source of truth; one OpenAI Conversation stores each thread's provider-side state; Azure Key Vault and managed identity supply production secrets.

**Tech Stack:** Python 3.12, FastAPI, Chainlit, OpenAI Agents SDK, OpenAI Python SDK, SQLAlchemy 2 async, asyncpg, Alembic, Jinja2, Argon2id, pytest, Ruff, mypy, Playwright, Azure App Service B3, Azure PostgreSQL Flexible Server, Azure Key Vault, GitHub Actions OIDC.

## Global Constraints

- Product and page name is **Project Recovery**; shared-resource administration is named **Knowledge**, never Organizational Knowledge.
- Do not include Salesforce, MyClubHub, BGCMD, School Harbor, billing, ticketing, glossary, customer branding, or customer data.
- Models are exactly `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`; default is `gpt-5.6-terra`.
- Reasoning efforts are exactly `low`, `medium`, and `high`; default is `medium`.
- Agents SDK tracing is enabled by default with `trace_include_sensitive_data=False`.
- Chat history and application telemetry have no automatic expiry.
- Both bootstrap accounts are administrators and must change their initial random passwords.
- Never print, commit, or place plaintext secrets in workflow files.
- Use only `az-amusheno.ps1` for Azure CLI access and verify `amusheno@outlook.com` before mutations.
- Production has no in-memory persistence fallback.
- Every page is paginated/bounded and provides no large export.

---

## File map

The implementation creates these focused units:

- `pyproject.toml`: dependencies and tool configuration.
- `.gitignore`: protects local inputs, generated credentials, caches, builds, and environment files.
- `src/project_recovery/config.py`: typed settings and allowed model policy.
- `src/project_recovery/app.py`: FastAPI factory, middleware, health routes, and Chainlit mount.
- `src/project_recovery/db.py`: async engine/session lifecycle only.
- `src/project_recovery/models.py`: SQLAlchemy persistence models only.
- `src/project_recovery/repositories/`: one repository module per feature group.
- `src/project_recovery/auth/`: password, session, cookie, role, and request dependencies.
- `src/project_recovery/chat_app.py`: Chainlit callbacks and streaming UI orchestration.
- `src/project_recovery/chainlit_data.py`: `BaseDataLayer` adapter.
- `src/project_recovery/agent_runtime.py`: Agents SDK configuration, OpenAI Conversation execution, tracing, and normalized events.
- `src/project_recovery/admin/`: approved admin routes and view models.
- `src/project_recovery/knowledge/`: vector-store ingestion and deletion.
- `src/project_recovery/templates/`: Jinja pages.
- `src/project_recovery/static/`: shared design tokens, CSS, and small JavaScript.
- `alembic/`: versioned PostgreSQL migrations.
- `scripts/`: local setup, bootstrap, Azure provisioning, deployment, and smoke verification.
- `tests/`: unit, integration, and browser tests mirroring source responsibilities.

### Task 1: Safe project foundation and configuration

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/project_recovery/__init__.py`
- Create: `src/project_recovery/config.py`
- Create: `tests/unit/test_config.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: environment variables and Key Vault-reference values injected by Azure App Service.
- Produces: `Settings`, `ModelId`, `ReasoningEffort`, `ALLOWED_MODELS`, and `get_settings()`.

- [ ] **Step 1: Protect every local secret before staging any source**

Add explicit ignore entries:

```gitignore
.env
.env.*
!.env.example
local-secrets/
openai_api_service_key.txt
openai_vector_store_id.txt
az-amusheno.ps1
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
dist/
build/
*.zip
```

- [ ] **Step 2: Write failing configuration-policy tests**

```python
from project_recovery.config import ALLOWED_MODELS, Settings


def test_model_policy_is_generic_and_terra_is_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_VECTOR_STORE_ID", "vs_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("APP_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "y" * 32)
    settings = Settings()
    assert settings.default_model == "gpt-5.6-terra"
    assert ALLOWED_MODELS == (
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    )
    assert settings.default_reasoning_effort == "medium"
```

- [ ] **Step 3: Run the focused test and confirm the missing module failure**

Run: `pytest tests/unit/test_config.py -q`
Expected: collection fails because `project_recovery.config` does not exist.

- [ ] **Step 4: Add typed settings and tooling**

Implement `Settings` with `pydantic-settings`, `@lru_cache get_settings()`, required production secrets, environment normalization, exact model/reasoning literals, and test-friendly construction. Configure Python 3.12, pytest, Ruff, and mypy in `pyproject.toml`.

Core policy:

```python
from typing import Literal

ModelId = Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
ReasoningEffort = Literal["low", "medium", "high"]
ALLOWED_MODELS: tuple[ModelId, ...] = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
)
ALLOWED_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = ("low", "medium", "high")
```

- [ ] **Step 5: Verify the foundation**

Run: `pytest tests/unit/test_config.py -q && ruff check src tests && mypy src`
Expected: all commands pass.

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml README.md src/project_recovery tests/unit/test_config.py
git commit -m "build: establish safe project foundation"
```

### Task 2: PostgreSQL schema, migrations, and repositories

**Files:**
- Create: `src/project_recovery/db.py`
- Create: `src/project_recovery/models.py`
- Create: `src/project_recovery/repositories/users.py`
- Create: `src/project_recovery/repositories/chat.py`
- Create: `src/project_recovery/repositories/telemetry.py`
- Create: `src/project_recovery/repositories/knowledge.py`
- Create: `src/project_recovery/repositories/__init__.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/20260811_0001_initial.py`
- Create: `tests/unit/test_models.py`
- Create: `tests/integration/test_repositories.py`

**Interfaces:**
- Consumes: `Settings.database_url`.
- Produces: `Database`, ORM records, `UserRepository`, `ChatRepository`, `TelemetryRepository`, and `KnowledgeRepository`.

- [ ] **Step 1: Write failing schema invariants**

Assert that:

```python
def test_conversations_have_no_expiry_column():
    assert "expires_at" not in Conversation.__table__.columns


def test_prompt_runs_link_trace_and_conversation():
    assert {"conversation_id", "trace_id", "model", "status"} <= {
        column.name for column in PromptRun.__table__.columns
    }
```

Add integration tests that create a user, conversation, message, prompt run, tool run, feedback row, exception, and knowledge row inside a transaction and retrieve each through its repository.

- [ ] **Step 2: Run tests against a disposable PostgreSQL database**

Run: `pytest tests/unit/test_models.py tests/integration/test_repositories.py -q`
Expected: fail because models and repositories are missing.

- [ ] **Step 3: Implement the async database boundary**

`Database` exposes:

```python
class Database:
    def __init__(self, url: str) -> None: ...
    def session(self) -> async_sessionmaker[AsyncSession]: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...
```

Use UUID primary keys, timezone-aware timestamps, bounded text columns, JSONB only for sanitized structured metadata, foreign keys, and indexes for page filters. Do not add automatic retention fields.

- [ ] **Step 4: Implement versioned initial migration**

Create all approved tables plus indexes and constraints. Alembic must upgrade a blank database and downgrade cleanly in an isolated test database.

- [ ] **Step 5: Implement repository methods used by later tasks**

Required methods include:

```python
await users.get_by_email(email)
await users.create(email, display_name, password_hash, roles, force_password_change)
await users.list_page(query, status, offset, limit)
await chats.create_thread(user_id, chainlit_thread_id, openai_conversation_id, settings)
await chats.append_message(conversation_id, role, content, provider_response_id)
await chats.list_user_threads(user_id, offset, limit)
await telemetry.start_prompt_run(...)
await telemetry.finish_prompt_run(...)
await telemetry.record_tool_run(...)
await telemetry.record_exception(...)
await knowledge.create_queued(...)
await knowledge.transition(resource_id, expected_status, new_status, ...)
```

- [ ] **Step 6: Verify migrations and repositories**

Run: `alembic upgrade head && pytest tests/unit/test_models.py tests/integration/test_repositories.py -q`
Expected: migration and tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/project_recovery/db.py src/project_recovery/models.py src/project_recovery/repositories alembic.ini alembic tests
git commit -m "feat: add durable PostgreSQL persistence"
```

### Task 3: Authentication, bootstrap administrators, and login audit

**Files:**
- Create: `src/project_recovery/auth/passwords.py`
- Create: `src/project_recovery/auth/sessions.py`
- Create: `src/project_recovery/auth/dependencies.py`
- Create: `src/project_recovery/auth/routes.py`
- Create: `src/project_recovery/auth/__init__.py`
- Create: `scripts/bootstrap_users.py`
- Create: `tests/unit/auth/test_passwords.py`
- Create: `tests/integration/auth/test_login.py`

**Interfaces:**
- Consumes: `UserRepository`, database session factory, and `Settings.app_session_secret`.
- Produces: `AuthService`, `CurrentUser`, `require_user`, `require_admin`, login/logout/password-change routes, and the ignored credentials file.

- [ ] **Step 1: Write failing security tests**

Cover Argon2id hashes, non-recoverable stored session-token hashes, Secure/HttpOnly/SameSite cookie flags in production, inactive-user denial, 12-hour idle expiry, administrator enforcement, login audit persistence, and forced password change.

Example:

```python
def test_password_hash_is_argon2id(password_service):
    encoded = password_service.hash("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert password_service.verify(encoded, "correct horse battery staple")
```

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/unit/auth tests/integration/auth -q`
Expected: fail on missing auth modules.

- [ ] **Step 3: Implement authentication services and routes**

Generate 32-byte session tokens, store only SHA-256 token hashes, rotate on login, revoke on logout/password change, and record last-seen updates with write throttling. Redact credentials from exceptions.

- [ ] **Step 4: Implement idempotent bootstrap**

`scripts/bootstrap_users.py`:

- creates both approved emails as admins only when absent;
- generates 20+ character passwords with `secrets`;
- sets `force_password_change=True`;
- writes plaintext once to `local-secrets/bootstrap-credentials.txt`;
- refuses to overwrite an existing credentials file;
- never prints passwords.

- [ ] **Step 5: Verify**

Run: `pytest tests/unit/auth tests/integration/auth -q && python scripts/bootstrap_users.py --help`
Expected: tests pass and help contains no secret values.

- [ ] **Step 6: Commit**

```bash
git add src/project_recovery/auth scripts/bootstrap_users.py tests
git commit -m "feat: add secure authentication and user bootstrap"
```

### Task 4: Application shell, shared navigation, Settings, Users, and Logins

**Files:**
- Create: `src/project_recovery/app.py`
- Create: `src/project_recovery/admin/shell.py`
- Create: `src/project_recovery/admin/settings.py`
- Create: `src/project_recovery/admin/users.py`
- Create: `src/project_recovery/admin/logins.py`
- Create: `src/project_recovery/admin/__init__.py`
- Create: `src/project_recovery/templates/base.html`
- Create: `src/project_recovery/templates/login.html`
- Create: `src/project_recovery/templates/settings.html`
- Create: `src/project_recovery/templates/users.html`
- Create: `src/project_recovery/templates/logins.html`
- Create: `src/project_recovery/static/app.css`
- Create: `src/project_recovery/static/app.js`
- Create: `tests/unit/test_navigation.py`
- Create: `tests/integration/test_admin_access.py`

**Interfaces:**
- Consumes: auth dependencies, repositories, and `Settings`.
- Produces: `create_app()`, `/health/live`, `/health/ready`, `/settings`, `/admin/users`, and `/admin/logins`.

- [ ] **Step 1: Write failing route/access tests**

Verify anonymous redirects, user/admin navigation differences, CSRF protection on writes, bounded pagination, user actions, Settings persistence, password change, and sanitized health responses.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/unit/test_navigation.py tests/integration/test_admin_access.py -q`
Expected: fail because application routes are absent.

- [ ] **Step 3: Build the application factory and middleware**

`create_app()` initializes repositories in lifespan, mounts static/templates, installs sanitized exception middleware, registers auth/admin routes, and redirects `/` to `/chat`. Readiness returns only component booleans and correlation IDs.

- [ ] **Step 4: Build functional pages**

Implement all approved Users and Logins actions and the personal Settings page. Every write requires a per-session CSRF token. Temporary passwords are shown once after an administrator action and are never stored plaintext.

- [ ] **Step 5: Add the calm shared design system**

Define CSS tokens for warm off-white, slate, muted sage/teal, desaturated blue, amber, rose, focus rings, spacing, reduced motion, and AA contrast. Use semantic HTML and keyboard-operable controls.

- [ ] **Step 6: Verify**

Run: `pytest tests/unit/test_navigation.py tests/integration/test_admin_access.py -q && ruff check src tests`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/project_recovery/app.py src/project_recovery/admin src/project_recovery/templates src/project_recovery/static tests
git commit -m "feat: add application shell and account administration"
```

### Task 5: OpenAI Agents SDK runtime, Conversations, file search, and tracing

**Files:**
- Create: `src/project_recovery/agent_runtime.py`
- Create: `src/project_recovery/costs.py`
- Create: `tests/unit/test_agent_runtime.py`
- Create: `tests/integration/test_agent_runtime_live.py`

**Interfaces:**
- Consumes: approved model policy, OpenAI API key, vector store ID, `ChatRepository`, and `TelemetryRepository`.
- Produces: `AgentRuntime.start_conversation()`, `AgentRuntime.stream_turn()`, `AgentEvent`, and `RunSummary`.

- [ ] **Step 1: Write failing unit tests with a fake runner**

Assert:

- `FileSearchTool` receives only the configured vector store;
- Terra/medium is default;
- invalid model/effort is rejected before an API call;
- `RunConfig` sets `tracing_disabled=False`, `trace_include_sensitive_data=False`, workflow name, group ID, trace ID, and non-PII metadata;
- usage and file-search tool events normalize into telemetry records;
- provider failure finishes the prompt run as failed.

- [ ] **Step 2: Run unit tests**

Run: `pytest tests/unit/test_agent_runtime.py -q`
Expected: fail because runtime types are missing.

- [ ] **Step 3: Implement one focused agent**

Core construction:

```python
from openai.types.shared import Reasoning
from agents import Agent, FileSearchTool, ModelSettings

Agent(
    name="Project Recovery Assistant",
    instructions=GENERIC_ASSISTANT_INSTRUCTIONS,
    model=model,
    model_settings=ModelSettings(reasoning=Reasoning(effort=effort)),
    tools=[FileSearchTool(vector_store_ids=[vector_store_id], max_num_results=5)],
)
```

Create the OpenAI Conversation explicitly with `AsyncOpenAI.conversations.create()`, persist its ID, then use `OpenAIConversationsSession(conversation_id=stored_id)` for each run.

- [ ] **Step 4: Implement streamed execution**

Use `Runner.run_streamed`, process raw text deltas for Chainlit, normalize tool-call/tool-output/message events, read `result.context_wrapper.usage`, and return:

```python
@dataclass(frozen=True)
class RunSummary:
    final_output: str
    provider_response_id: str | None
    trace_id: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
```

- [ ] **Step 5: Verify with unit and opt-in live tests**

Run: `pytest tests/unit/test_agent_runtime.py -q`
Run when `RUN_OPENAI_LIVE_TESTS=1`: `pytest tests/integration/test_agent_runtime_live.py -q`
Expected: mocked tests always pass; live test creates a disposable conversation, receives a response, observes a trace ID, and deletes disposable objects where supported.

- [ ] **Step 6: Commit**

```bash
git add src/project_recovery/agent_runtime.py src/project_recovery/costs.py tests
git commit -m "feat: integrate OpenAI Agents runtime and tracing"
```

### Task 6: Chainlit chat, durable history, settings, feedback, and attachments

**Files:**
- Create: `src/project_recovery/chat_app.py`
- Create: `src/project_recovery/chainlit_data.py`
- Create: `.chainlit/config.toml`
- Create: `public/chat-navigation.css`
- Create: `public/chat-navigation.js`
- Create: `tests/unit/test_chainlit_data.py`
- Create: `tests/integration/test_chat_flow.py`

**Interfaces:**
- Consumes: `AuthService`, `ChatRepository`, `AgentRuntime`, and `TelemetryRepository`.
- Produces: Chainlit password authentication, chat lifecycle callbacks, persistent threads/steps/feedback, streaming, resume, and private attachments.

- [ ] **Step 1: Write failing data-layer and callback tests**

Test all `BaseDataLayer` methods Chainlit calls for users, threads, steps, elements, and feedback; verify ownership filtering, JSON-serializable settings restoration, no expiry, and administrator navigation.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/unit/test_chainlit_data.py tests/integration/test_chat_flow.py -q`
Expected: fail because the adapter and callbacks are absent.

- [ ] **Step 3: Implement the Chainlit data adapter**

Map Chainlit IDs to repository IDs without duplicating message content. Implement `close()` and bounded `list_threads()`. Reject cross-user thread access.

- [ ] **Step 4: Implement callbacks**

Provide:

```python
@cl.password_auth_callback
async def authenticate(username: str, password: str) -> cl.User | None: ...

@cl.on_chat_start
async def on_chat_start() -> None: ...

@cl.on_settings_update
async def on_settings_update(settings: dict[str, str]) -> None: ...

@cl.on_message
async def on_message(message: cl.Message) -> None: ...

@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None: ...
```

Stream normalized text deltas, render file citations, persist messages and attachments, and expose feedback actions.

- [ ] **Step 5: Mount Chainlit and share navigation styles**

Call:

```python
mount_chainlit(app=app, target="src/project_recovery/chat_app.py", path="/chat")
```

The Settings navigation button opens `/settings`; admin links match only approved pages; no domain branding appears.

- [ ] **Step 6: Verify**

Run: `pytest tests/unit/test_chainlit_data.py tests/integration/test_chat_flow.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/project_recovery/chat_app.py src/project_recovery/chainlit_data.py .chainlit public tests
git commit -m "feat: add durable Chainlit chat experience"
```

### Task 7: Prompt Runs, Feedback, Model Usage, Exceptions, and Tool Use

**Files:**
- Create: `src/project_recovery/admin/prompt_runs.py`
- Create: `src/project_recovery/admin/feedback.py`
- Create: `src/project_recovery/admin/model_usage.py`
- Create: `src/project_recovery/admin/exceptions.py`
- Create: `src/project_recovery/admin/tool_use.py`
- Create: `src/project_recovery/templates/prompt_runs.html`
- Create: `src/project_recovery/templates/chat_feedback.html`
- Create: `src/project_recovery/templates/model_usage.html`
- Create: `src/project_recovery/templates/exceptions.html`
- Create: `src/project_recovery/templates/tool_use.html`
- Create: `tests/integration/test_telemetry_pages.py`

**Interfaces:**
- Consumes: `TelemetryRepository` and `require_admin`.
- Produces: `/admin/prompt-runs`, `/admin/chat-feedback`, `/admin/model-usage`, `/admin/exceptions`, and `/admin/tool-use`.

- [ ] **Step 1: Write failing page tests**

Seed two users and multiple runs; verify admin-only access, pagination, supported time windows, aggregate correctness, trace linkage, context truncation, secret redaction, and absence of export endpoints.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/integration/test_telemetry_pages.py -q`
Expected: fail because routes/templates are missing.

- [ ] **Step 3: Implement bounded query/view models**

Use page sizes no larger than 100. Usage aggregates must calculate request/user/conversation counts, token categories, latency, estimated cost, and unpriced counts from `prompt_runs`. Tool output and exception context must be redacted before rendering.

- [ ] **Step 4: Register routes and navigation**

All five pages require `admin`; all links use the approved generic names.

- [ ] **Step 5: Verify**

Run: `pytest tests/integration/test_telemetry_pages.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/project_recovery/admin src/project_recovery/templates tests/integration/test_telemetry_pages.py
git commit -m "feat: add operational administration pages"
```

### Task 8: Knowledge ingestion and vector-store lifecycle

**Files:**
- Create: `src/project_recovery/knowledge/service.py`
- Create: `src/project_recovery/knowledge/routes.py`
- Create: `src/project_recovery/knowledge/__init__.py`
- Create: `src/project_recovery/templates/knowledge.html`
- Create: `src/project_recovery/static/knowledge.js`
- Create: `tests/unit/knowledge/test_service.py`
- Create: `tests/integration/knowledge/test_routes.py`

**Interfaces:**
- Consumes: `KnowledgeRepository`, `AsyncOpenAI`, configured vector store ID, and `require_admin`.
- Produces: `/admin/knowledge`, `/admin/knowledge/status`, upload, retry, and delete operations.

- [ ] **Step 1: Write failing lifecycle tests**

Cover allowed extensions, 25 MB maximum, safe filename handling, queued/processing/ready/error transitions, idempotent retry, OpenAI cleanup on partial failure, full deletion of vector-store/file objects, and restart recovery of stale processing records.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/unit/knowledge tests/integration/knowledge -q`
Expected: fail because the service is absent.

- [ ] **Step 3: Implement the durable state machine**

Allowed transitions:

```text
queued -> processing -> ready
queued -> processing -> error
error -> queued
processing(stale) -> queued
ready -> deleting -> deleted
error -> deleting -> deleted
```

Persist state before provider calls. Upload with sanitized category/description attributes. Poll ingestion with bounded backoff. Delete both the vector-store attachment and provider file, recording any cleanup error.

- [ ] **Step 4: Implement functional UI**

Provide upload, search, status filter, polling, retry, and confirmed delete. Use the name **Knowledge** exclusively.

- [ ] **Step 5: Verify**

Run: `pytest tests/unit/knowledge tests/integration/knowledge -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/project_recovery/knowledge src/project_recovery/templates/knowledge.html src/project_recovery/static/knowledge.js tests
git commit -m "feat: add shared Knowledge management"
```

### Task 9: Browser QA, accessibility, security, and integrated verification

**Files:**
- Create: `tests/e2e/test_login_chat_admin.py`
- Create: `tests/e2e/test_accessibility.py`
- Create: `tests/security/test_redaction.py`
- Create: `scripts/run_local.ps1`
- Modify: `README.md`

**Interfaces:**
- Consumes: the complete local application.
- Produces: release-blocking smoke, accessibility, and redaction evidence.

- [ ] **Step 1: Write browser acceptance tests**

Use Playwright to verify login, forced password change, new chat, model settings, history resume, Settings, every named admin page, user creation/reset/deactivation, feedback, and Knowledge upload UI with provider calls mocked.

- [ ] **Step 2: Add accessibility assertions**

Check keyboard navigation, visible focus, labels, landmarks, no serious axe violations, reduced-motion behavior, and AA contrast for the approved palette.

- [ ] **Step 3: Add security regression tests**

Inject API keys, authorization headers, cookies, database URLs, and passwords into simulated failures/tool output; assert they never appear in logs, HTML, trace metadata, or JSON responses.

- [ ] **Step 4: Run the full local release gate**

Run:

```powershell
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
python -m build
```

Expected: all pass.

- [ ] **Step 5: Perform browser QA against the running app**

Run: `playwright test` or the repository's pytest Playwright command.
Expected: all browser tests pass at desktop and narrow viewport sizes.

- [ ] **Step 6: Commit**

```bash
git add tests scripts/run_local.ps1 README.md
git commit -m "test: add integrated release verification"
```

### Task 10: Azure provisioning, CI/CD, deployment, and production proof

**Files:**
- Create: `startup.sh`
- Create: `scripts/azure/provision.ps1`
- Create: `scripts/azure/configure.ps1`
- Create: `scripts/azure/deploy.ps1`
- Create: `scripts/azure/smoke.ps1`
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/deploy.yml`
- Create: `docs/operations/azure-deployment.md`
- Create: `tests/unit/test_deployment_assets.py`

**Interfaces:**
- Consumes: `az-amusheno.ps1`, local OpenAI input files, built application artifact, and the approved Azure subscription.
- Produces: B3 Web App, PostgreSQL Flexible Server, Key Vault configuration, OIDC deployment, verified production URL, and durable credentials file.

- [ ] **Step 1: Write deployment-asset tests**

Verify scripts:

- invoke Azure only through the wrapper;
- assert the active user is `amusheno@outlook.com`;
- never echo secret variables;
- create Basic B3 Linux App Service;
- enable HTTPS, WebSockets, Always On, system identity, and health path;
- use Key Vault references;
- configure PostgreSQL B1ms/32 GiB/seven-day backup/no HA or the closest available low-cost SKU;
- use `alembic upgrade head` before server start;
- contain a post-deploy health and login smoke test.

- [ ] **Step 2: Run asset tests**

Run: `pytest tests/unit/test_deployment_assets.py -q`
Expected: fail because scripts/workflows are absent.

- [ ] **Step 3: Implement idempotent provisioning/configuration**

Use explicit resource IDs returned from Azure. Generate names safely, check global availability, and persist non-secret deployment metadata to `local-secrets/azure-deployment.json`. Create secrets from files without printing values. Assign the Web App identity `Key Vault Secrets User`.

- [ ] **Step 4: Provision resources**

Run:

```powershell
.\scripts\azure\provision.ps1
.\scripts\azure\configure.ps1
```

Expected: resource group contains B3 plan, Linux Web App, PostgreSQL server/database, Key Vault references, identity/RBAC, and optional modest-cost Application Insights.

- [ ] **Step 5: Bootstrap database and users**

Run migrations and `scripts/bootstrap_users.py` through a safe production configuration path. Confirm `local-secrets/bootstrap-credentials.txt` exists without printing it.

- [ ] **Step 6: Deploy**

Build a clean artifact from tracked files only and run:

```powershell
.\scripts\azure\deploy.ps1
```

Expected: Azure reports successful deployment and the Web App restarts healthy.

- [ ] **Step 7: Verify production**

Run:

```powershell
.\scripts\azure\smoke.ps1
```

Verify `/health/live`, `/health/ready`, login, forced-password-change behavior without consuming both bootstrap credentials, all admin routes, real Terra chat streaming, OpenAI Conversation reuse, vector-store file search, trace emission, database persistence across restart, and sanitized App Service logs.

- [ ] **Step 8: Configure and validate GitHub Actions OIDC**

Create the federated credential and repository variables/secrets required by `.github/workflows/deploy.yml`, push `main`, and confirm both test and deploy workflows pass.

- [ ] **Step 9: Final review and merge**

Run the full release gate again, review `git diff` and commit history, merge approved work to `main`, push, wait for deployment, and rerun production smoke verification.

- [ ] **Step 10: Commit**

```bash
git add startup.sh scripts/azure .github/workflows docs/operations tests/unit/test_deployment_assets.py
git commit -m "ops: add Azure deployment and production verification"
```

## Final evidence checklist

- [ ] Design and plan contain no placeholders or domain-specific leakage.
- [ ] Local secret inputs and generated credentials are ignored and untracked.
- [ ] Unit, integration, browser, accessibility, security, lint, type, and build gates pass.
- [ ] Independent code and security review findings are resolved.
- [ ] Both approved administrator rows exist and require password changes.
- [ ] Production default is Terra/medium; Luna and Sol are selectable.
- [ ] Chat continuity survives Web App restart using the same OpenAI Conversation.
- [ ] PostgreSQL history survives restart and has no expiry.
- [ ] File search uses the configured vector store.
- [ ] Agents SDK traces show model and tool activity without sensitive trace data.
- [ ] Every approved page is functional, access-controlled, paginated, and generically branded.
- [ ] Azure deployment and GitHub Actions deployment both succeed.
- [ ] Production smoke tests pass after the final deployment.
- [ ] User receives the production URL and clickable local credential-file path.
