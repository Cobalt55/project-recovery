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

Provision the remaining West US 3 stack: PostgreSQL Flexible Server,
VNet/private DNS, and a new Key Vault. The provisioning script validates and
reuses the existing `project-recovery-westus3-rg` resource group,
`project-recovery-westus3-b3-plan` Basic B3 Linux App Service plan, and
`project-recovery-chat-wus3-amush` Linux Web App. It checks regional App
Service quota only if that plan must be created. Then configure its managed
identity, Key Vault references, HTTPS, TLS 1.2, WebSockets, Always On, and the
readiness health path:

The remaining resources use stable names so a failed run can resume safely:
`project-recovery-kv-wus3` for Key Vault and
`project-recovery-pg-wus3-amush` for PostgreSQL. In-progress metadata is saved
before the first remaining resource mutation; reruns validate/reuse resources
and reset the PostgreSQL administrator password before replacing the database
connection secret.

```powershell
.\scripts\azure\provision.ps1
.\scripts\azure\configure.ps1
```

The scripts persist only resource names and IDs to
`local-secrets/azure-deployment.json`. It is ignored by Git. Local OpenAI input
files are read directly into Key Vault and are never printed.

The deployment intentionally does not reuse the pre-existing resource group or
Key Vault in another region. All application resources and their private
networking are co-located in West US 3.

The PostgreSQL Flexible Server uses `Standard_B1ms`, 32 GiB storage, seven-day
backup retention, and no high availability. It has no public endpoint: a
delegated PostgreSQL subnet and private DNS zone are created in the deployment
VNet, and the Web App uses a separate delegated subnet through regional VNet
integration. The database password is generated unless supplied as a secure
PowerShell value, then stored only as a Key Vault secret.

## Initial database setup and credentials

`startup.sh` runs `alembic upgrade head` before Uvicorn begins serving requests.
The configured `BOOTSTRAP_CREDENTIALS_PATH` is inside the Web App's persistent
`/home/data` mount. On the first start only, it creates the two approved
administrator accounts and writes the credential handoff there. `deploy.ps1`
waits for that file, downloads it to the ignored, current-user-only local path
`local-secrets/bootstrap-credentials.txt`, then deletes the remote plaintext
before the smoke test. Reruns preserve the local handoff and attempt remote
deletion again; passwords are never printed or committed.

## Deploy and smoke verification

Deploy only a clean worktree. The script builds a zip from tracked files,
restarts the Web App, retrieves the one-time bootstrap handoff securely, and
invokes the non-destructive smoke checks:

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
