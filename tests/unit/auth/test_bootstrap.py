"""Local bootstrap credential-file safety coverage."""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from bootstrap_users import write_credentials_once  # noqa: E402


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
