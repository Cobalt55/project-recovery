# Task 3 Report — Authentication, bootstrap administrators, and login audit

## Scope

- Argon2id password service and opaque, SHA-256-hashed server-side sessions.
- Active-user, revocation, exact 12-hour idle-expiry, CSRF, force-password-change, and admin gates.
- Login audit persistence and secure production cookie policy.
- A write-once bootstrap flow for only `pricejfl@gmail.com` and `alecmusheno@gmail.com`.
- The `20260811_0002` migration adds separately hashed CSRF secrets without a duplicate default on populated databases.

## RED / GREEN evidence

The interrupted implementation recorded the following intentional red-to-green cycles before this continuation:

1. Auth test collection was RED while the auth modules were absent, then GREEN after the password, session, dependencies, routes, and bootstrap implementation was added.
2. The exact 12-hour idle-boundary regression was RED because the boundary was accepted; it became GREEN with the `>= SESSION_IDLE_TIMEOUT` expiry check.
3. The direct `change_password` invalid-session regression was RED; it became GREEN after that method independently rejects revoked, inactive, and idle-expired sessions.
4. A populated pre-`0002` database migration was RED because a shared/default backfill violated the unique CSRF-hash constraint; it became GREEN after the migration backfilled a fresh cryptographic hash per legacy row before setting `NOT NULL` and the unique constraint.

At resumption, one remaining failure was a test-fixture error rather than product behavior: `database.session()` returns an `async_sessionmaker`, so the test must call the maker before entering it. The fixture was corrected from `async with database.session()` to `async with database.session()()`.

Final GREEN verification on 2026-08-11:

```text
pytest tests/unit/auth tests/integration/auth -q
14 passed in 20.92s

pytest tests/integration/auth/test_login.py::test_csrf_migration_upgrades_populated_legacy_sessions -q
1 passed in 12.17s

python scripts/bootstrap_users.py --help
usage: bootstrap_users.py [-h] [--credentials-file CREDENTIALS_FILE]
...

ruff check src/project_recovery/auth scripts/bootstrap_users.py tests/unit/auth tests/integration/auth
All checks passed!
```

## Bootstrap verification

An isolated runtime check replaced the database/repository boundary with an in-memory test double and exercised `bootstrap` itself. It verified that:

- exactly the two approved addresses are requested, in the approved list order;
- both created accounts receive only the `admin` role and `force_password_change=True`;
- each generated password is at least 20 characters;
- the credential handoff is created once with exclusive file creation; and
- the bootstrap function emits no stdout and a second invocation with the same handoff path raises `FileExistsError`.

The command exited 0 and used a temporary directory that was removed after the check; no credentials were printed or retained.

## Notes

- Session and CSRF bearer values are generated independently and only their SHA-256 representations are persisted.
- Production session cookies are `Secure`, `HttpOnly`, `SameSite=Lax`, and `Path=/`; CSRF uses a separate non-HttpOnly value.
- The existing task-local lint defects were limited to import/line formatting and were corrected before final verification.
