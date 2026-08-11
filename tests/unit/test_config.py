from project_recovery.config import ALLOWED_MODELS, Settings


def test_model_policy_is_generic_and_terra_is_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_VECTOR_STORE_ID", "vs_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("APP_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "y" * 32)
    settings = Settings()
    assert settings.default_model == "gpt-5.6-terra"
    assert ALLOWED_MODELS == (
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    )
    assert settings.default_reasoning_effort == "medium"
