"""Local bootstrap credential-file safety coverage."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import bootstrap_users  # noqa: E402
from bootstrap_users import DEFAULT_CREDENTIALS_FILE, ROOT, write_credentials_once  # noqa: E402


def test_bootstrap_credentials_are_written_once_without_stdout(tmp_path, capsys) -> None:
    """The handoff file is exclusive and the console never receives passwords."""
    destination = tmp_path / "bootstrap-credentials.txt"
    credentials = [("pricejfl@gmail.com", "A-secret-password-value")]

    write_credentials_once(destination, credentials)

    assert destination.read_text(encoding="utf-8") == (
        "Bootstrap administrator credentials\n\npricejfl@gmail.com: A-secret-password-value\n"
    )
    assert capsys.readouterr().out == ""
    with pytest.raises(FileExistsError):
        write_credentials_once(destination, credentials)


def test_default_bootstrap_handoff_is_anchored_under_the_repository_root() -> None:
    """Changing the process directory cannot redirect the default plaintext handoff."""
    assert DEFAULT_CREDENTIALS_FILE == ROOT / "local-secrets" / "bootstrap-credentials.txt"


def test_windows_acl_failure_prevents_plaintext_file_creation(
    tmp_path, monkeypatch, capsys
) -> None:
    """Windows bootstrap fails closed if its containing directory ACL cannot be restricted."""
    destination = tmp_path / "local-secrets" / "bootstrap-credentials.txt"
    monkeypatch.setattr(bootstrap_users.os, "name", "nt")
    monkeypatch.setattr(
        bootstrap_users.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", "denied"),
    )

    with pytest.raises(PermissionError, match="ACL"):
        write_credentials_once(destination, [("pricejfl@gmail.com", "secret")])

    assert not destination.exists()
    assert capsys.readouterr().out == ""


def test_windows_acl_is_restricted_before_exclusive_plaintext_creation(
    tmp_path, monkeypatch
) -> None:
    """Windows applies a current-user-only directory ACL before opening the credential file."""
    destination = tmp_path / "local-secrets" / "bootstrap-credentials.txt"
    calls: list[object] = []
    original_open = os.open
    monkeypatch.setattr(bootstrap_users.os, "name", "nt")
    monkeypatch.setattr(bootstrap_users.getpass, "getuser", lambda: "operator")
    monkeypatch.setattr(
        bootstrap_users.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(("icacls", args, kwargs))
        or subprocess.CompletedProcess(args[0], 0, "", ""),
    )
    def record_open(*args, **kwargs):
        calls.append(("open", args, kwargs))
        return original_open(*args, **kwargs)

    monkeypatch.setattr(bootstrap_users.os, "open", record_open)

    write_credentials_once(destination, [("pricejfl@gmail.com", "secret")])

    assert calls[0][0] == "icacls"
    assert calls[1][0] == "open"
