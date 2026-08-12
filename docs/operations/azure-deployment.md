# Azure deployment

Project Recovery is deployed to the subscription for `amusheno@outlook.com` only.
The deployment assets intentionally use the local `az-amusheno.ps1` wrapper for
every Azure CLI request. Never replace it with a direct Azure CLI invocation.

## One-time provisioning

From the repository worktree, confirm the approved wrapper is present at
`C:\Users\amush\Repositories\project-recovery\az-amusheno.ps1`. The scripts
assert its active identity before any mutation.

Run the safe plan mode first; it changes nothing and never reads secret values:

```powershell
.\scripts\azure\provision.ps1 -Plan
.\scripts\azure\configure.ps1 -Plan
```

Provision the East US 2 Basic B3 Linux App Service, then configure its managed
identity, Key Vault references, HTTPS, TLS 1.2, WebSockets, Always On, and the
readiness health path:

```powershell
.\scripts\azure\provision.ps1
.\scripts\azure\configure.ps1
```

The scripts persist only resource names and IDs to
`local-secrets/azure-deployment.json`. It is ignored by Git. Local OpenAI input
files are read directly into Key Vault and are never printed.

The PostgreSQL Flexible Server uses `Standard_B1ms`, 32 GiB storage, seven-day
backup retention, and no high availability. The database password is generated
unless supplied as a secure PowerShell value, then stored only as a Key Vault
secret. Before production traffic, restrict PostgreSQL networking to the Web
App's outbound addresses (and any explicitly approved migration path); do not
open a broad public firewall rule.

## Initial database setup and credentials

`startup.sh` runs `alembic upgrade head` before Uvicorn begins serving requests.
After the first healthy deployment, run `scripts/bootstrap_users.py` in a
production environment where the five application settings resolve from Key
Vault. The resulting local handoff is
`local-secrets/bootstrap-credentials.txt`; it is plaintext, access-controlled,
ignored by Git, and must never be uploaded or pasted into logs.

## Deploy and smoke verification

Deploy only a clean worktree. The script builds a zip from tracked files,
restarts the Web App, and invokes the non-destructive smoke checks:

```powershell
.\scripts\azure\deploy.ps1
.\scripts\azure\smoke.ps1
```

The smoke check requires one unused bootstrap credential, verifies both health
endpoints, and confirms that the initial login requires a password change. It
does not print the credential.

## GitHub Actions OIDC

Create a GitHub OIDC application/federated credential constrained to this
repository's `main` branch and grant it the narrowest role that can deploy the
existing Web App. Configure these repository environment variables for the
`production` environment:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_WEBAPP_NAME`
- `AZURE_APP_URL` (for example, `https://name.azurewebsites.net`)

The workflow has no static Azure secret. It runs tests, linting, and type checks
before an OIDC-authenticated deployment and then waits for `/health/ready`.
