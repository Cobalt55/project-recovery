# Project Recovery

Project Recovery is a calm, authenticated workspace for knowledge-backed chat and
operations. It is designed for durable history, shared knowledge, and safe
administration.

## Development setup

Use Python 3.12 or newer and install the package with its development tools:

```text
python -m pip install -e ".[dev]"
```

The application reads configuration from environment variables (or a local
`.env` file). The following values are required: `OPENAI_API_KEY`,
`OPENAI_VECTOR_STORE_ID`, `DATABASE_URL`, `APP_SESSION_SECRET`, and
`CHAINLIT_AUTH_SECRET`. Keep local values out of source control; the repository
ignore rules cover environment files and local secret directories.

The supported models are `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`,
with Terra and medium reasoning as the defaults. Tracing is enabled by default,
while sensitive trace data is disabled.

## Run locally

Create `.env.local` with the five required variable names shown above (keep the
values out of source control), then start the app from PowerShell:

```powershell
.\scripts\run_local.ps1 -Port 8000
```

The helper runs Alembic migrations and keeps Uvicorn in the foreground. To create
the two approved administrator accounts exactly once, pass `-BootstrapAdmins`;
their generated passwords are written only to the ignored
`local-secrets/bootstrap-credentials.txt` handoff file. The bootstrap command
prints a count, never a password.

## Verification

The local release gate is:

```powershell
python -m pytest -q
ruff check src tests scripts
ruff format --check src tests scripts
mypy src
python -m build
```

The HTTP smoke tests in `tests/e2e` are opt-in. Set `E2E_BASE_URL`,
`E2E_EMAIL`, and `E2E_PASSWORD` in the process environment before running
`python -m pytest -q tests/e2e/test_login_chat_admin.py`; test output never
prints those values. The tests cover sign-in, settings validation, Chat, every
approved admin page, and the model/reasoning controls. They skip when the
variables are absent so normal development runs remain offline.

For browser-level QA, use a real browser against the same URL and verify visible
focus, keyboard navigation, reduced-motion behavior, and the calm rose/plum and
teal palette at desktop and narrow widths.
