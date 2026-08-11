# PostgreSQL Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable PostgreSQL-backed records, migrations, and repositories for users, chat, telemetry, and knowledge.

**Architecture:** SQLAlchemy async owns the database engine/session lifecycle; declarative ORM models define bounded, indexed relational records using UUIDs and UTC-aware timestamps. Alembic creates and removes the schema, while focused repositories provide the application-facing bounded queries and status transitions.

**Tech Stack:** Python 3.12, SQLAlchemy async, asyncpg, PostgreSQL 16, Alembic, pytest/pytest-asyncio.

## Global Constraints

- PostgreSQL is the product source of truth; production has no in-memory fallback.
- History and telemetry have no expiry fields; timestamps are UTC-aware.
- Repository page queries are bounded; sensitive structured context is redacted and size-bounded.
- JSONB stores only sanitized structured metadata; all database columns use bounded text where applicable.
- Use generic product terminology only; never print or commit secrets.

---

### Task 1: Model and database boundary

**Files:**
- Create: `tests/unit/test_models.py`
- Create: `src/project_recovery/models.py`
- Create: `src/project_recovery/db.py`
- Modify: `pyproject.toml`

- [ ] Write schema invariant tests, run them against missing models, and observe an import failure.
- [ ] Add async SQLAlchemy models and `Database`, then rerun the model tests to green.

### Task 2: Repositories and PostgreSQL behavior

**Files:**
- Create: `tests/integration/test_repositories.py`
- Create: `src/project_recovery/repositories/__init__.py`
- Create: `src/project_recovery/repositories/users.py`
- Create: `src/project_recovery/repositories/chat.py`
- Create: `src/project_recovery/repositories/telemetry.py`
- Create: `src/project_recovery/repositories/knowledge.py`

- [ ] Write an integration test for creation/retrieval and status transitions, run it against the missing repositories, and observe failure.
- [ ] Implement the minimal repositories over a disposable PostgreSQL 16 database and rerun to green.

### Task 3: Versioned migration and verification

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/20260811_0001_initial.py`

- [ ] Write migration round-trip coverage, run it without Alembic files, and observe failure.
- [ ] Implement the initial migration, run upgrade/downgrade against a blank disposable database, then run the focused tests and Ruff.
- [ ] Commit the task and record test evidence in the task report.
