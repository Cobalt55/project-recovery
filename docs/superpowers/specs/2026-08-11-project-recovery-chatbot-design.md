# Project Recovery Chatbot Design

Date: 2026-08-11  
Status: Approved for implementation

## 1. Purpose

Project Recovery is a clean-slate, generic, production-oriented Chainlit chatbot. It keeps the strongest reusable product patterns from the `salesforce-mcp` reference application while excluding all Salesforce, MyClubHub, BGCMD, School Harbor, billing-validation, ticketing, glossary, and customer-specific behavior.

The MVP must:

- run as a lightweight Python application on Azure App Service;
- use the OpenAI Agents SDK as the only agent runtime;
- keep Agents SDK tracing enabled by default and connect application telemetry to trace identifiers;
- use the existing OpenAI vector store for shared knowledge;
- store each durable chat as an OpenAI Conversation;
- retain application chat history indefinitely unless a future administrator explicitly deletes it;
- provide functional implementations of Chat, Settings, Users, Logins, Prompt Runs, Chat Feedback, Model Usage, Exceptions, Knowledge, and Tool Use;
- provide two administrator accounts at launch;
- use safe, comforting, accessible visual design;
- support repeatable deployment and operational verification.

## 2. Considered approaches

### A. Modular monolith: FastAPI + mounted Chainlit + PostgreSQL

One FastAPI process owns authentication, admin routes, persistence, and application lifecycle. Chainlit is mounted at `/chat`. PostgreSQL stores users, application history, and operational telemetry. OpenAI Conversations store model-side conversation state.

Advantages:

- one B3 Web App, one deployment artifact, and one operational boundary;
- direct reuse of the reference application's proven route/repository patterns;
- admin and chat features share authentication and persistence;
- focused modules remain independently testable;
- lowest deployment and maintenance complexity for the requested scope.

Trade-offs:

- the application must carefully bridge Chainlit authentication and the FastAPI admin workspace;
- long-running ingestion must be designed so a Web App restart cannot corrupt state.

### B. Separate chat and admin services

Run Chainlit and the admin application as separate Azure Web Apps backed by a shared database.

Advantages:

- independent scaling and failure domains;
- clearer runtime separation.

Trade-offs:

- doubles deployment, configuration, authentication, and observability work;
- materially higher cost and operational burden;
- unnecessary for the expected MVP load.

### C. Chainlit-only application with minimal custom pages

Use Chainlit's UI and data layer for almost everything, adding only small custom links.

Advantages:

- quickest initial chat deployment;
- smallest amount of custom frontend code.

Trade-offs:

- cannot cleanly deliver the requested functional admin workspace;
- current official Chainlit persistence migrations require careful compatibility handling;
- creates awkward boundaries for user management and operational reporting.

### Decision

Use approach A, the modular monolith. It best balances simplicity, cost, maintainability, and functional completeness.

## 3. System architecture

### 3.1 Runtime

- Python 3.12
- FastAPI application factory
- Chainlit mounted at `/chat`
- Uvicorn production server
- Jinja2 templates and small, framework-free JavaScript for admin pages
- SQLAlchemy 2 async ORM with `asyncpg`
- Alembic versioned migrations
- OpenAI Agents SDK (`openai-agents`)
- OpenAI Python SDK for Conversations, vector-store administration, and file lifecycle operations not surfaced directly by the Agents SDK

The FastAPI application owns startup checks, database connectivity, migrations, authentication dependencies, exception recording, health endpoints, and the admin workspace. Chainlit owns the streaming chat experience.

### 3.2 Module boundaries

The source package will be organized by responsibility:

- `app`: application factory, middleware, health endpoints, Chainlit mounting;
- `config`: typed environment configuration and secret references;
- `db`: engine lifecycle, models, migrations, and repository protocols;
- `auth`: password hashing, sessions, cookies, roles, and login history;
- `chat`: Chainlit callbacks, chat settings, streaming, resumption, feedback actions, and attachment handling;
- `agents`: agent factory, model policy, hosted file-search configuration, tracing helpers, and result normalization;
- `admin`: routes and view models for the approved admin pages;
- `knowledge`: shared-vector-store file ingestion and deletion;
- `telemetry`: prompt runs, usage, tool activity, exceptions, trace linkage, and cost calculation;
- `users`: account administration, password reset, activation, and role changes.

Routes depend on service/repository interfaces rather than issuing SQL directly. Modules may change their internal implementation without changing their consumers.

## 4. Identity, authentication, and authorization

### 4.1 Accounts

Bootstrap these accounts:

- `pricejfl@gmail.com`
- `alecmusheno@gmail.com`

Both are administrators. Each receives a cryptographically random initial password and must change it at first login.

The plaintext bootstrap credentials are written once to a local ignored file:

`local-secrets/bootstrap-credentials.txt`

Only password hashes are stored in PostgreSQL. The local file is never committed or deployed.

### 4.2 Passwords and sessions

- Passwords use Argon2id through a maintained password-hashing library.
- Temporary passwords are at least 20 random printable characters.
- Authentication cookies are HTTP-only, Secure in production, SameSite=Lax, and rotated on login.
- Session tokens are random; only token hashes are stored.
- Interactive sessions expire after 12 hours of inactivity, while the login audit record remains.
- Logout and administrator revocation immediately invalidate the stored session.
- Rate limiting applies to login and password-reset endpoints.
- There is no public registration.

### 4.3 Roles

MVP roles:

- `admin`: access to all approved admin pages and all application telemetry;
- `user`: access only to the user's own chats and personal settings.

The Users page can create users, generate temporary passwords, reset passwords, activate/deactivate users, and assign `admin` or `user`. It does not send email in the MVP.

## 5. Chat and Agents SDK behavior

### 5.1 Chat lifecycle

Each new Chainlit thread:

1. creates an application conversation row;
2. creates one OpenAI Conversation;
3. stores the OpenAI conversation ID on the application conversation;
4. persists user and assistant messages locally for history, reporting, and recovery;
5. uses the same OpenAI Conversation for every subsequent turn;
6. records the Agents SDK trace ID and run telemetry for each turn.

OpenAI Conversation items provide durable OpenAI-side state without the ordinary response object's 30-day TTL. PostgreSQL remains the product source of truth for user-visible history and admin reporting.

### 5.2 Agent

The MVP uses one focused generic agent. It has:

- concise, neutral, helpful system instructions;
- the hosted OpenAI file-search tool connected to the configured vector store;
- no Salesforce or customer-specific tools;
- explicit tool and turn limits;
- streaming output;
- a stable safety identifier derived from an internal user UUID rather than email.

The design intentionally avoids unnecessary multi-agent orchestration.

### 5.3 Models and settings

Allowed models:

- `gpt-5.6-luna`
- `gpt-5.6-terra`
- `gpt-5.6-sol`

Default model: `gpt-5.6-terra`  
Default reasoning effort: `medium`

Allowed reasoning efforts:

- `low`
- `medium`
- `high`

The in-chat settings panel changes the active thread settings. The dedicated Settings page controls personal defaults, theme preference, and password changes. Defaults are persisted per user.

### 5.4 Tracing

Agents SDK tracing remains enabled by default. Every run uses:

- workflow name `Project Recovery Chat`;
- group identifier equal to the internal conversation UUID;
- metadata containing only non-PII internal identifiers, selected model, and environment;
- custom spans around knowledge lookup normalization and application persistence;
- stored trace ID on the prompt-run record.

Tracing failures must not prevent a chat response. The admin UI shows trace identifiers and links when a safe dashboard URL can be constructed, but never exposes OpenAI API keys or raw authentication data.

### 5.5 Attachments

Users may attach common documents and images to a chat. Conversation attachments are private to that conversation and are not added to the shared vector store. Metadata is retained with the chat; temporary provider files are cleaned up when safe.

Shared organizational material is uploaded only through the Knowledge page.

## 6. Persistence model

PostgreSQL tables:

- `users`
- `login_sessions`
- `user_management_events`
- `conversations`
- `messages`
- `message_attachments`
- `prompt_runs`
- `tool_runs`
- `chat_feedback`
- `exception_logs`
- `knowledge_resources`
- `app_settings`
- `alembic_version`

Important rules:

- chat history has no automatic expiration;
- application telemetry is retained indefinitely for the MVP;
- timestamps are stored in UTC;
- user-facing queries are paginated and bounded;
- large exception contexts and tool outputs are truncated and redacted;
- OpenAI keys, passwords, session tokens, database passwords, and cookies are never logged;
- aggregates for Model Usage are calculated from `prompt_runs`, avoiding redundant summary tables.

## 7. Functional pages

### 7.1 Chat

- authenticated Chainlit experience;
- searchable/resumable history;
- streaming answers;
- file-search citations where available;
- per-thread model and reasoning settings;
- private attachments;
- thumbs-up/down feedback with optional comment;
- navigation to Settings and administrator pages when authorized.

### 7.2 Settings

- personal default model;
- personal default reasoning effort;
- light/dark/system theme preference;
- password change;
- clear explanation that changes affect new chats unless changed in-chat.

### 7.3 Users

- list/search/filter users;
- create account and generate a temporary password;
- change roles;
- deactivate/reactivate;
- reset password and force change at next login;
- show created and last-login timestamps;
- record user-management audit events.

### 7.4 Logins

- paginated login-session history;
- user, login time, last seen, expiry, status, and revocation;
- no token or cookie values.

### 7.5 Prompt Runs

- paginated user prompt history;
- conversation, user, model, requested/effective reasoning effort, status, latency, tokens, estimated cost, trace ID, and timestamp;
- prompt text displayed with safe truncation and expansion.

### 7.6 Chat Feedback

- rating, optional comment, user, conversation, and timestamp;
- bounded context snapshot with the triggering prompt and assistant response;
- associated model, trace, and tool summary.

### 7.7 Model Usage

- time windows of 24 hours, 7 days, 30 days, 90 days, and all time;
- requests, conversations, users, input/cached/output/total tokens, latency, and estimated cost;
- grouped views by user and model;
- no bulk export.

### 7.8 Exceptions

- paginated, redacted application exceptions;
- timestamp, request path, authenticated user ID, exception type/message, occurrence count, and stack trace;
- grouping by stable exception fingerprint;
- no secrets, cookies, authorization headers, or sensitive query values.

### 7.9 Knowledge

- named simply **Knowledge** everywhere;
- list/search/filter resources by status;
- upload PDF, DOCX, TXT, or Markdown files up to 25 MB;
- category and description metadata;
- visible queued, processing, ready, and error states;
- add files to the existing OpenAI vector store;
- delete resource metadata and the corresponding OpenAI vector-store/file objects;
- durable ingestion state so restarts leave recoverable queued/error records;
- no domain-specific glossary or organization concepts.

### 7.10 Tool Use

- paginated Agents SDK tool-call history;
- tool name/type, conversation, user, status, duration, result count/summary, trace ID, and timestamp;
- file-search activity is included;
- tool arguments and outputs are redacted and size-bounded;
- no bulk export.

## 8. Visual design

The visual language is quiet, safe, and reassuring:

- warm off-white and soft slate surfaces;
- muted sage/teal primary color;
- desaturated blue for informational states;
- gentle amber and rose reserved for warnings/errors;
- WCAG AA contrast for text and controls;
- 8 px spacing rhythm, generous whitespace, and moderate corner radii;
- clear focus rings and keyboard navigation;
- minimal motion that respects `prefers-reduced-motion`;
- plain-language labels and calm empty/error states;
- no customer logos, gradients that reduce readability, aggressive red, or distracting animation.

Chainlit custom CSS/JavaScript and the admin templates share design tokens so the product feels coherent.

## 9. Error handling and reliability

- A global FastAPI exception middleware writes sanitized exceptions to PostgreSQL.
- Expected validation/authentication failures are not recorded as server exceptions.
- OpenAI, vector-store, and database errors receive user-safe messages plus internal correlation IDs.
- Transient OpenAI operations use bounded exponential backoff.
- A failed telemetry write cannot discard a successful assistant response; it is logged and surfaced through health diagnostics.
- Knowledge ingestion state transitions are idempotent.
- `/health/live` verifies the process.
- `/health/ready` verifies database access and required configuration without exposing values.
- Startup fails clearly when production database or required secrets are unavailable; there is no in-memory production fallback.

## 10. Azure design

Use the verified subscription belonging to `amusheno@outlook.com`.

Region: East US 2  
Resource group: existing `recovery-az-web-app_group`

Resources:

- Linux Azure Web App with an available hostname based on `project-recovery-chat`;
- Basic B3 App Service plan;
- Azure Database for PostgreSQL Flexible Server, burstable B1ms or the nearest currently available low-cost equivalent, 32 GiB storage, seven-day backups, and no high availability for MVP;
- existing `recovery-az-key-vault`;
- system-assigned managed identity on the Web App;
- Application Insights if it can be enabled within a modest additional budget.

Security/configuration:

- HTTPS only, TLS 1.2 or newer, WebSockets enabled, Always On enabled;
- API key, database password/URL, Chainlit auth secret, and application session secret stored in Key Vault;
- Web App reads Key Vault secrets with managed identity;
- vector store ID stored as configuration or a Key Vault secret;
- PostgreSQL firewall restricted to required App Service outbound addresses and deployment/migration paths;
- no secret values committed to Git or placed directly in workflow files.

## 11. Delivery

### 11.1 Repository safety

Before implementation:

- ignore the existing local API-key/vector-store files, Azure wrapper, generated credentials, `.env` files, caches, and build artifacts;
- never print or commit secret values;
- preserve the provided Azure wrapper locally.

### 11.2 CI/CD

- tests, linting, type checking, and migration validation run before deployment;
- initial deployment is performed and verified directly;
- GitHub Actions uses Azure OIDC for repeatable deployments from `main`;
- deployment health is checked after restart;
- a production chat/login/admin smoke test confirms real functionality.

### 11.3 Completion criteria

The project is complete when:

- all approved pages are functional and access-controlled;
- both bootstrap administrators can log in and are forced to change passwords;
- chat streams from the default Terra model;
- Luna, Terra, and Sol settings work;
- OpenAI Conversation continuity survives restart;
- vector-store file search works and produces citations;
- traces appear for model and tool calls;
- application history survives restart and has no automatic expiry;
- automated tests pass;
- the application is merged to `main`;
- Azure deployment reports healthy;
- production smoke tests pass;
- the local bootstrap-credential file path and production URL are handed to the user.

## 12. Explicit non-goals

- Salesforce, MCP-to-Salesforce, MyClubHub, BGCMD, School Harbor, billing, core metrics, ticketing, glossary, scheduled monitors, or customer branding;
- public user registration;
- outbound email;
- large exports or bulk reporting;
- multi-tenant organization isolation;
- high-availability database topology;
- multiple cooperating agents;
- advanced eval management UI.
