import tomllib
from pathlib import Path

from pydantic import SecretStr

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


def test_database_url_is_secret_and_redacted(monkeypatch):
    database_url = "postgresql+asyncpg://db-user:db-password@localhost/project_recovery"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_VECTOR_STORE_ID", "vs_test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "y" * 32)

    settings = Settings()

    assert isinstance(settings.database_url, SecretStr)
    assert settings.database_url.get_secret_value() == database_url
    assert "db-password" not in repr(settings)
    assert "db-password" not in str(settings)


def test_mypy_uses_normal_import_following():
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        mypy_config = tomllib.load(pyproject_file)["tool"]["mypy"]

    assert mypy_config.get("follow_imports", "normal") == "normal"


def test_mypy_skip_override_is_scoped_to_pydantic_settings():
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        mypy_config = tomllib.load(pyproject_file)["tool"]["mypy"]

    overrides = mypy_config["overrides"]
    assert overrides == [
        {
            "module": ["pydantic_settings", "pydantic_settings.*"],
            "follow_imports": "skip",
        }
    ]
