# Project Recovery Frontend and QA Rounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply two evidence-driven frontend improvement rounds to Project Recovery, verify each round locally and in production, and preserve the existing Chainlit/FastAPI architecture.

**Architecture:** Keep Chainlit as the chat client and FastAPI/Jinja as the account/admin client. Fix verified defects through existing callbacks, shared server-rendered shell components, responsive CSS, and one bounded Chainlit customization script; add repository/query behavior only where bounded pagination needs it. Browser QA is the product acceptance gate.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Chainlit 2.11.x, PostgreSQL/SQLAlchemy, vanilla CSS/JavaScript, pytest, Playwright, Azure App Service, GitHub Actions.

## Global Constraints

- Follow the approved design at `docs/superpowers/specs/2026-08-13-frontend-qa-rounds-design.md`.
- Use an 80/20 approach: preserve Chainlit and Jinja; do not introduce React, Vite, a custom chat renderer, or a second state layer.
- Retain generic Project Recovery branding and never introduce Salesforce, MyClubHub, BGCMD, or School Harbor terminology or assets.
- Keep Terra as the default model and Luna/Terra/Sol plus low/medium/high reasoning available.
- Do not add exports or speculative integrations.
- Use TDD: each production behavior begins with a failing focused test.
- No required route may have document-level horizontal overflow at 390, 768, 1280, or 1440 pixels.
- All icon-only controls must have explicit accessible names; each conversation-history row must expose one primary keyboard stop.
- Preserve durable Chat history, existing authentication/CSRF behavior, OpenAI tracing, vector search, and requested admin functionality.
- Use `C:\Users\amush\Repositories\project-recovery\az-amusheno.ps1` for Azure CLI operations and verify `amusheno@outlook.com` before Azure mutation.
- Store screenshots/traces outside the repository; commit only the three approved concept references.

---

### Task 1: Complete Chainlit logout

**Files:**
- Create: `src/project_recovery/auth/cookies.py`
- Modify: `src/project_recovery/app.py`
- Modify: `src/project_recovery/chat_app.py`
- Test: `tests/integration/test_chat_flow.py`
- Test: `tests/integration/test_admin_access.py`

**Interfaces:**
- Produce `SESSION_COOKIE`, `CSRF_COOKIE`, `CHAINLIT_COOKIE_PREFIX`, `set_login_cookies(response, ...)`, and `clear_login_cookies(response, request)` in `auth/cookies.py`.
- Register `@cl.on_logout async def on_logout(request: Request, response: Response) -> None`.
- Preserve `POST /logout` as the CSRF-protected Jinja logout endpoint.

- [ ] **Step 1: Add failing cookie-helper and Chainlit callback tests**

Add a callback test using Starlette `Request`/`Response` objects:

```python
@pytest.mark.asyncio
async def test_chainlit_logout_revokes_application_session_and_clears_all_auth_cookies():
    request = make_request(
        "project_recovery_session=active-token; "
        "project_recovery_csrf=csrf-token; access_token=jwt"
    )
    response = Response()
    await chat_app.on_logout(request, response)
    assert auth.logged_out == ["active-token"]
    set_cookie = response.headers.getlist("set-cookie")
    assert_cookie_deleted(set_cookie, "project_recovery_session")
    assert_cookie_deleted(set_cookie, "project_recovery_csrf")
    assert_cookie_deleted(set_cookie, "access_token")
```

Extend the TestClient flow so `POST /chat/logout` is followed by `/settings`, `/admin/logins`, and `/chat/project/threads`; protected HTML routes must redirect to `/login` and the project endpoint must return 401.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
pytest tests/integration/test_chat_flow.py tests/integration/test_admin_access.py -q
```

Expected: failures show no Chainlit logout callback and application cookies remain usable.

- [ ] **Step 3: Extract cookie policy and implement the callback**

Move cookie constants and helper bodies from `app.py` into `auth/cookies.py`. Import them back into `app.py` without changing login/password-change semantics.

In `chat_app.py`:

```python
@cl.on_logout
async def on_logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        await get_chat_dependencies().auth.logout(token)
    clear_login_cookies(response, request)
```

The callback must not log tokens or return an HTML redirect to Chainlit's XHR request.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Run auth regression tests**

Run:

```powershell
pytest tests/unit/auth tests/integration/auth tests/integration/test_chat_flow.py tests/integration/test_admin_access.py -q
ruff check src/project_recovery/auth src/project_recovery/app.py src/project_recovery/chat_app.py tests/integration
```

- [ ] **Step 6: Commit**

```powershell
git add src/project_recovery/auth/cookies.py src/project_recovery/app.py src/project_recovery/chat_app.py tests/integration/test_chat_flow.py tests/integration/test_admin_access.py
git commit -m "fix: complete logout across chat and admin"
```

---

### Task 2: Build the shared responsive Jinja workspace shell

**Files:**
- Modify: `src/project_recovery/admin/shell.py`
- Modify: `src/project_recovery/app.py`
- Modify: `src/project_recovery/templates/base.html`
- Modify: `src/project_recovery/static/app.css`
- Modify: `src/project_recovery/static/app.js`
- Test: `tests/unit/test_navigation.py`
- Test: `tests/e2e/test_accessibility.py`

**Interfaces:**
- Extend `NavigationItem` with `group: Literal["workspace", "admin"]`.
- `/api/navigation` serializes `label`, `href`, `active`, and `group`.
- Jinja shell uses `data-drawer-open`, `data-drawer-close`, `data-drawer`, and `data-drawer-backdrop`.

- [ ] **Step 1: Write failing navigation and accessibility contract tests**

Assert personal items use group `workspace`, admin items use group `admin`, and the API includes the group/current state.

Add template/static assertions for:

```python
assert 'aria-label="Open navigation"' in base
assert 'aria-label="Close navigation"' in base
assert 'data-drawer-backdrop' in base
assert "ADMIN" not in visible_customer_copy
assert "@media (max-width: 900px)" in css
assert "aria-modal" in base
```

Use visible label `Admin`, not uppercase decorative copy.

- [ ] **Step 2: Run tests and verify RED**

```powershell
pytest tests/unit/test_navigation.py tests/e2e/test_accessibility.py tests/integration/test_admin_access.py -q
```

- [ ] **Step 3: Implement grouped navigation and shell markup**

Render:

- a skip link to `#main-content`,
- desktop rail with Project Recovery, workspace group, and labeled Admin group,
- mobile 44-pixel menu button,
- closed-by-default overlay drawer/backdrop,
- existing account email and CSRF logout form.

Do not change role visibility or route ordering.

- [ ] **Step 4: Implement drawer behavior in `app.js`**

Use one small controller that:

- opens/closes the drawer,
- closes on Escape/backdrop,
- traps Tab within the open drawer,
- restores focus to the opener,
- toggles `aria-expanded`, `aria-hidden`, and page scroll locking.

- [ ] **Step 5: Implement approved design tokens and responsive shell CSS**

Use the spec's off-white/white/slate/plum/teal tokens, 8-pixel rhythm, 44-pixel controls, persistent desktop rail, and overlay drawer at `max-width: 900px`. Remove horizontal-scrolling navigation and ensure `.workspace`, `main`, and tables use `min-width: 0`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 2 command plus:

```powershell
ruff check src/project_recovery/admin src/project_recovery/app.py tests
ruff format --check src/project_recovery/admin src/project_recovery/app.py tests
```

- [ ] **Step 7: Commit**

```powershell
git add src/project_recovery/admin/shell.py src/project_recovery/app.py src/project_recovery/templates/base.html src/project_recovery/static/app.css src/project_recovery/static/app.js tests/unit/test_navigation.py tests/e2e/test_accessibility.py
git commit -m "feat: add responsive workspace shell"
```

---

### Task 3: Make Logins bounded and responsive

**Files:**
- Modify: `src/project_recovery/app.py`
- Modify: `src/project_recovery/admin/shell.py`
- Modify: `src/project_recovery/admin/users.py`
- Modify: `src/project_recovery/repositories/users.py`
- Modify: `src/project_recovery/templates/logins.html`
- Modify: `src/project_recovery/static/app.css`
- Modify: `src/project_recovery/static/app.js`
- Test: `tests/integration/test_admin_access.py`
- Test: `tests/e2e/test_accessibility.py`

**Interfaces:**
- `list_logins(offset: int, limit: int, query: str | None = None, status: str | None = None)`.
- Route accepts bounded `offset`, `limit` in `{25, 50, 100}`, `query`, and `status` in `{"active", "revoked", "expired", "all"}`.
- Route fetches `limit + 1` and passes `logins[:limit]`, `has_next`, `previous_offset`, and retained filters.

- [ ] **Step 1: Write failing pagination/filter/rendering tests**

Cover:

- limit clamping,
- page-size plus-one lookahead,
- retained query/status in Prev/Next links,
- revoked/expired/active filtering,
- mobile session-row markup,
- desktop primary columns,
- UUID/exact values inside `<details>`,
- existing CSRF revoke behavior,
- absence of token/hash/cookie values.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
pytest tests/integration/test_admin_access.py tests/e2e/test_accessibility.py -q
```

- [ ] **Step 3: Add bounded repository filtering**

Normalize query with `strip().casefold()` and bound it before using `User.email.ilike`. Status predicates:

- active: user active, no `revoked_at`, `expires_at > utc_now()`
- revoked: `revoked_at is not null`
- expired: not revoked and `expires_at <= utc_now()`
- all: no status predicate

Return only the existing secret-free projection.

- [ ] **Step 4: Render desktop and mobile presentations**

Desktop table primary columns: User, Status, Signed in, Last active, Expires. Put exact timestamps, IDs, and revoke action inside a row `<details>`.

Mobile uses `.session-list`/`.session-row`; never display the desktop table below 768 pixels. Both presentations share the same server rows.

- [ ] **Step 5: Add safe revoke confirmation and friendly timestamp hooks**

Add `data-confirm="Revoke this session?"` to revoke forms and handle it in `app.js`. Render `<time datetime="...">` with exact ISO value available through `datetime` and details.

- [ ] **Step 6: Run tests and verify GREEN**

Run the Step 2 command, then:

```powershell
pytest tests/integration/test_repositories.py -q
ruff check src tests
mypy src
```

- [ ] **Step 7: Commit**

```powershell
git add src/project_recovery/app.py src/project_recovery/admin src/project_recovery/repositories/users.py src/project_recovery/templates/logins.html src/project_recovery/static tests/integration/test_admin_access.py tests/e2e/test_accessibility.py
git commit -m "feat: make login activity responsive and bounded"
```

---

### Task 4: Apply the 80/20 Chainlit workspace customization

**Files:**
- Modify: `.chainlit/config.toml`
- Modify: `.chainlit/translations/en-US.json`
- Modify: `public/chat-navigation.css`
- Modify: `public/chat-navigation.js`
- Modify: `tests/integration/test_chat_flow.py`
- Modify: `tests/e2e/test_accessibility.py`

**Interfaces:**
- Use one `MutationObserver` and idempotent `enhance(root)` function.
- Inject one `#project-recovery-nav` shell/drawer populated from `/api/navigation`.
- Attribute hooks: `data-pr-enhanced`, `data-pr-drawer-open`, `data-pr-drawer-close`.

- [ ] **Step 1: Inspect the pinned Chainlit DOM in a disposable local/test browser**

Record stable selectors by roles, IDs already observed in production, and accessible structure. Prefer:

- known IDs such as `upload-button`, `chat-settings-open-modal`, `chat-submit`,
- button purpose and SVG ancestry,
- route/href patterns for history.

Do not select hashed classes.

- [ ] **Step 2: Add failing static contract tests**

Assert:

- no fixed bottom navigation CSS,
- Project Recovery empty-state/composer copy exists,
- control-label map covers sidebar/search/new chat/upload/settings/send/account,
- history nested buttons are removed from tab order,
- Send and Stop receive different labels,
- drawer has explicit open/close names,
- no forbidden customer terms.

- [ ] **Step 3: Run focused tests and verify RED**

```powershell
pytest tests/integration/test_chat_flow.py tests/e2e/test_accessibility.py -q
```

- [ ] **Step 4: Implement the approved Chat visual system**

Replace the floating bottom bar with a desktop rail/integrated navigation and a closed mobile overlay drawer. Reserve composer/history space. Restyle Chainlit surfaces using documented custom CSS; do not vendor or replace Chainlit components.

Use translation/config entries for product name and placeholder where Chainlit supports them. Only use DOM text replacement for the central default brand/empty state when there is no stable public config.

- [ ] **Step 5: Implement accessible behavior shim**

Idempotently:

- apply explicit accessible names and 44-pixel targets,
- make each history row one primary tab stop by setting nested redundant button `tabindex="-1"` and `aria-hidden="true"` only when it duplicates the parent thread link,
- label dialog content with title/description when missing,
- expose distinct `Send message` and `Stop response` states,
- ignore a second Send activation during the transition into streaming,
- preserve native settings, streaming, history, feedback, and attachment behavior.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 3 command and:

```powershell
ruff check tests/integration/test_chat_flow.py tests/e2e/test_accessibility.py
```

- [ ] **Step 7: Commit**

```powershell
git add .chainlit public tests/integration/test_chat_flow.py tests/e2e/test_accessibility.py
git commit -m "feat: unify and harden the chat workspace"
```

---

### Task 5: Run local Browser QA round 1 and fix only failed scenarios

**Files:**
- Create outside repository: local QA screenshots and traces
- Modify only files implicated by reproduced failures
- Test: relevant focused tests from Tasks 1–4

**Interfaces:**
- Local URL: `http://127.0.0.1:8000`
- Test roles: anonymous and admin
- Viewports: 390×844, 768×1024, 1280×800, 1440×1000

- [ ] **Step 1: Prepare isolated local configuration**

Use a disposable PostgreSQL 16 database, run Alembic migrations, and bootstrap the two approved admins into an ignored local credential file. Load existing OpenAI key/vector-store values without printing them. Start:

```powershell
.\scripts\run_local.ps1 -Port 8000
```

- [ ] **Step 2: Execute the round-one QA contract**

Browser path priority: Codex Desktop Browser, then approved Playwright fallback if attachment is unavailable.

Exercise:

- login and both logout surfaces,
- protected-page denial after logout/reload/back,
- Chat send/stream/settings/history/reload,
- rapid double Send,
- keyboard-only drawer/history/settings/account,
- Logins filters/pagination/details/revoke confirmation without confirming,
- all requested admin routes,
- console and failed requests,
- all four viewports.

- [ ] **Step 3: Capture and classify findings**

Record exact reproduction, expected/actual, screenshot/DOM evidence, severity, and ownership outside the repository. A Critical/P1 or hard fail blocks deployment.

- [ ] **Step 4: Fix findings through TDD**

For each reproducible code defect:

1. add a failing focused automated test,
2. run it RED,
3. implement the smallest fix,
4. run it GREEN,
5. rerun its browser scenario plus one happy-path regression.

- [ ] **Step 5: Run the full local gate**

```powershell
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
python -m build
git diff --check
```

- [ ] **Step 6: Commit round-one QA fixes**

```powershell
git add src/project_recovery public .chainlit tests
git commit -m "fix: close local frontend QA findings"
```

---

### Task 6: Deploy round 1 and run independent production QA

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/deploy.yml`
- Test: `tests/unit/test_deployment_assets.py`

**Interfaces:**
- CI release gate also runs `ruff format --check src tests scripts` and `python -m build`.
- Azure app: `project-recovery-chat-wus3-amush`

- [ ] **Step 1: Add failing workflow contract tests**

Assert both workflows contain the complete quality/build gate and still use OIDC plus the existing Web App deployment.

- [ ] **Step 2: Run deployment asset tests and verify RED**

```powershell
pytest tests/unit/test_deployment_assets.py -q
```

- [ ] **Step 3: Update workflow gates minimally**

Add format/build commands only; do not change Azure resources, secrets, or deployment topology.

- [ ] **Step 4: Run the full gate and verify GREEN**

Use the Task 5 Step 5 command.

- [ ] **Step 5: Commit, merge, and push round 1**

Merge the verified branch into `main`, push `main`, and wait for GitHub Test and Deploy conclusions. Do not force-push.

- [ ] **Step 6: Verify Azure state**

Through the approved wrapper, confirm account `amusheno@outlook.com`, running West US 3 Web App, and `/health/ready` application/database booleans.

- [ ] **Step 7: Dispatch four independent production testers**

Use separate testers for:

- novice Chat/account/logout,
- admin operations,
- mobile/accessibility,
- messy/resilience behavior.

Avoid concurrent destructive actions. Each tester reports exact findings and does not modify code.

- [ ] **Step 8: Preserve production findings as round-two input**

No Critical/P1 finding may be deferred. Important findings enter Task 7 only if reproduced or supported by direct browser evidence.

---

### Task 7: Implement the evidence-driven round-two polish

**Files:**
- Modify: `src/project_recovery/admin/formatting.py`
- Modify: `src/project_recovery/admin/prompt_runs.py`
- Modify: `src/project_recovery/admin/tool_use.py`
- Modify: `src/project_recovery/chainlit_data.py`
- Modify: `src/project_recovery/templates/prompt_runs.html`
- Modify: `src/project_recovery/templates/tool_use.html`
- Modify: `src/project_recovery/static/app.js`
- Test: `tests/integration/test_telemetry_pages.py`
- Test: `tests/unit/test_chainlit_data.py`

**Interfaces:**
- `format_timestamp` renders exact ISO in `<time datetime>`; client JS may localize visible content through `Intl.DateTimeFormat`.
- `data-copy-value` and one shared `aria-live="polite"` status implement copy feedback.
- No external trace link exists unless a configured real trace base URL is added separately.

- [ ] **Step 1: Convert reproduced production findings into failing tests**

At minimum, cover already validated improvements if still present:

- friendly timestamp markup with exact value retained,
- trace/UUID copy affordances,
- identifiers moved into details,
- Prev/Next and bounded page size for Prompt Runs/Tool Use,
- stable history fallback names or empty-thread suppression that preserves deep links.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
pytest tests/integration/test_telemetry_pages.py tests/unit/test_chainlit_data.py tests/e2e/test_accessibility.py -q
```

- [ ] **Step 3: Implement only the tested polish**

Reuse shared CSS/JS/components from earlier tasks. Do not add exports, a new JS framework, speculative filters, or external trace navigation.

- [ ] **Step 4: Run focused and full gates**

Run Step 2, then the Task 5 Step 5 full gate.

- [ ] **Step 5: Run local Browser QA round 2**

Repeat all failed production scenarios, then Chat happy path, admin route smoke, keyboard pass, and all four viewports. Fix any new hard fail through one TDD loop.

- [ ] **Step 6: Commit**

```powershell
git add src/project_recovery/admin/formatting.py src/project_recovery/admin/prompt_runs.py src/project_recovery/admin/tool_use.py src/project_recovery/chainlit_data.py src/project_recovery/templates/prompt_runs.html src/project_recovery/templates/tool_use.html src/project_recovery/static/app.js tests/integration/test_telemetry_pages.py tests/unit/test_chainlit_data.py
git commit -m "feat: refine admin activity and chat history UX"
```

---

### Task 8: Deploy round 2 and complete final assurance

**Files:**
- No planned production-code files; fixes require a failing scenario and focused test
- Evidence remains outside repository

**Interfaces:**
- Final production URL: `https://project-recovery-chat-wus3-amush.azurewebsites.net`

- [ ] **Step 1: Merge/push the verified round-two commit**

Use the preapproved local merge/push workflow and wait for GitHub Test and Deploy success.

- [ ] **Step 2: Run Browser QA round 2 in production**

Dispatch the same four independent personas. Require PASS across Functionality, Integration, Robustness, and Completeness with no hard fail.

- [ ] **Step 3: Run final visual fidelity review**

Capture desktop Chat, desktop Logins, and mobile Chat/Logins. Use `view_image` on each approved concept and latest corresponding screenshot. Record at least five comparison points: shell/layout, typography, palette, navigation, responsive behavior, composer/table behavior, and accessibility affordances.

- [ ] **Step 4: Run final security/code review**

Use an independent high-assurance reviewer over the full branch/merge range. Resolve all Critical/Important findings through one tested fix wave and scoped re-review.

- [ ] **Step 5: Run fresh completion evidence**

```powershell
pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
python -m build
git diff --check
git status --short
```

Verify live readiness and GitHub run conclusions for the deployed `main` SHA.

- [ ] **Step 6: Clean the owned worktree and hand off**

After the merge/deploy is verified and the local credential file remains preserved in the main checkout, remove only this plan's owned `.worktrees/frontend-qa-rounds` worktree and merged feature branch.
