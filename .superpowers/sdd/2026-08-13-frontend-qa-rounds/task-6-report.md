# Task 6 — Workflow contract and release-gate slice

## Scope

Steps 1–4 only: verify the workflow contract, preserve the existing Azure OIDC/Web App topology, and ensure both CI workflows run the release quality and build gates.

## Result

The requested workflow changes are already present in the branch history in commit `eae87de` (`ci: add format and build release gates`). No additional workflow mutation was necessary: `.github/workflows/test.yml` and `.github/workflows/deploy.yml` both include:

- `pytest -q`
- `ruff check src tests`
- `ruff format --check src tests scripts`
- `mypy src`
- `python -m build`

The deployment workflow still uses `id-token: write`, `azure/login@v2`, `azure/webapps-deploy@v3`, the configured `AZURE_WEBAPP_NAME`, package `.` and the `/health/ready` readiness check. Azure resources, secrets, and deployment topology were not changed.

## Verification

- `pytest tests/unit/test_deployment_assets.py -q` — **20 passed**
- Workflow contract assertions cover both quality gates and deployment/OIDC invariants.

Steps 5–8 (merge/push, Azure verification, production QA, and round-two input) remain with the controller as requested.

## Concerns

The targeted test process exceeded the interactive polling interval while PowerShell-backed plan checks completed; it finished successfully in 12.27 seconds. No timeout or functional failure occurred.
