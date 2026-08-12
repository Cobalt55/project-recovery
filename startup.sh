#!/usr/bin/env bash
# App Service starts this command after a zip deployment.  Keep the migration
# before Uvicorn so a new release cannot receive traffic on an old schema.
set -euo pipefail

if [[ "${1:-}" == "--validate" || "${STARTUP_VALIDATE_ONLY:-}" == "1" ]]; then
  printf '%s\n' 'alembic upgrade head'
  printf '%s\n' 'if BOOTSTRAP_CREDENTIALS_PATH is set and its file is absent: python scripts/bootstrap_users.py --credentials-file "$BOOTSTRAP_CREDENTIALS_PATH"'
  printf '%s\n' 'uvicorn project_recovery.app:create_app'
  exit 0
fi

python -m alembic upgrade head
if [[ -n "${BOOTSTRAP_CREDENTIALS_PATH:-}" && ! -e "$BOOTSTRAP_CREDENTIALS_PATH" ]]; then
  python scripts/bootstrap_users.py --credentials-file "$BOOTSTRAP_CREDENTIALS_PATH"
fi
exec python -m uvicorn project_recovery.app:create_app --host 0.0.0.0 --port "${PORT:-8000}"
