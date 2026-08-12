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


def test_bootstrap_credentials_are_written_once_without_stdout(
    tmp_path, capsys, monkeypatch
) -> None:
    """The handoff file is exclusive and the console never receives passwords."""
    destination = tmp_path / "bootstrap-credentials.txt"
    credentials = [("pricejfl@gmail.com", "A-secret-password-value")]
    monkeypatch.setattr(bootstrap_users.os, "name", "posix")

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


def test_windows_acl_rejects_a_preexisting_extra_access_rule(tmp_path, monkeypatch) -> None:
    """A successful ACL command is insufficient when effective access includes another identity."""
    destination = tmp_path / "local-secrets" / "bootstrap-credentials.txt"
    monkeypatch.setattr(bootstrap_users.os, "name", "nt")
    monkeypatch.setattr(
        bootstrap_users.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            '{"valid": true, "canonical_path": "ignored", "dacl_protected": true, '
            '"current_full_control_rules": 1, "other_access_rules": 1}',
            "",
        ),
    )

    with pytest.raises(PermissionError, match="ACL"):
        write_credentials_once(destination, [("pricejfl@gmail.com", "secret")])

    assert not destination.exists()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows ACL support")
def test_windows_acl_owner_sid_validation_allows_the_current_owner(tmp_path) -> None:
    """The PowerShell ACL round-trip accepts a directory owned by the current SID."""
    destination = tmp_path / "local-secrets" / "bootstrap-credentials.txt"

    write_credentials_once(destination, [("pricejfl@gmail.com", "secret")])

    assert destination.read_text(encoding="utf-8").endswith("pricejfl@gmail.com: secret\n")


def test_windows_acl_rejects_an_owner_sid_that_differs_from_the_current_user(
    tmp_path, monkeypatch
) -> None:
    """A claimed valid ACL cannot permit plaintext when owner and caller SIDs differ."""
    destination = tmp_path / "local-secrets" / "bootstrap-credentials.txt"
    monkeypatch.setattr(bootstrap_users.os, "name", "nt")
    monkeypatch.setattr(
        bootstrap_users.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            '{"valid": true, "canonical_path": "'
            + str(destination.parent.resolve()).replace("\\", "\\\\")
            + '", "current_sid": "S-1-5-21-current", "owner_sid": "S-1-5-21-other", '
            '"dacl_protected": true, "current_full_control_rules": 1, '
            '"other_access_rules": 0}',
            "",
        ),
    )

    with pytest.raises(PermissionError, match="ACL"):
        write_credentials_once(destination, [("pricejfl@gmail.com", "secret")])

    assert not destination.exists()


def test_windows_acl_is_restricted_before_exclusive_plaintext_creation(
    tmp_path, monkeypatch
) -> None:
    """Windows applies a current-user-only directory ACL before opening the credential file."""
    destination = tmp_path / "local-secrets" / "bootstrap-credentials.txt"
    calls: list[object] = []
    original_open = os.open
    monkeypatch.setattr(bootstrap_users.os, "name", "nt")
    monkeypatch.setattr(
        bootstrap_users.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(("powershell", args, kwargs))
        or subprocess.CompletedProcess(
            args[0],
            0,
            '{"valid": true, "canonical_path": "'
            + str(destination.parent.resolve()).replace("\\", "\\\\")
            + '", "current_sid": "S-1-5-21-current", "owner_sid": "S-1-5-21-current", '
            '"dacl_protected": true, "current_full_control_rules": 1, '
            '"other_access_rules": 0}',
            "",
        ),
    )
    def record_open(*args, **kwargs):
        calls.append(("open", args, kwargs))
        return original_open(*args, **kwargs)

    monkeypatch.setattr(bootstrap_users.os, "open", record_open)

    write_credentials_once(destination, [("pricejfl@gmail.com", "secret")])

    assert calls[0][0] == "powershell"
    assert calls[0][1][0][0].casefold().endswith("powershell.exe")
    assert calls[0][2]["env"]["PROJECT_RECOVERY_CREDENTIALS_DIRECTORY"] == str(destination.parent)
    assert calls[1][0] == "open"
