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
