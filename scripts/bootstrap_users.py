"""Create the approved local administrators exactly once."""

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from project_recovery.auth.passwords import shared_password_service  # noqa: E402
from project_recovery.config import Settings  # noqa: E402
from project_recovery.db import Database  # noqa: E402
from project_recovery.repositories.users import UserRepository  # noqa: E402

APPROVED_ADMINS = ("pricejfl@gmail.com", "alecmusheno@gmail.com")
DEFAULT_CREDENTIALS_FILE = ROOT / "local-secrets" / "bootstrap-credentials.txt"


def generate_password() -> str:
    """Return an independently random password with at least 20 characters."""
    return secrets.token_urlsafe(24)


def write_credentials_once(path: Path, credentials: Iterable[tuple[str, str]]) -> None:
    """Exclusively create the local credential handoff without console output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        _restrict_windows_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("Bootstrap administrator credentials\n\n")
            for email, password in credentials:
                output.write(f"{email}: {password}\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _restrict_windows_directory(directory: Path) -> None:
    """Fail closed unless Windows grants the current user sole directory access."""
    environment = os.environ | {"PROJECT_RECOVERY_CREDENTIALS_DIRECTORY": str(directory)}
    script = """
$ErrorActionPreference = 'Stop'
$path = [Environment]::GetEnvironmentVariable('PROJECT_RECOVERY_CREDENTIALS_DIRECTORY')
if ([string]::IsNullOrWhiteSpace($path)) { throw 'credential directory is required' }
$resolved = (Resolve-Path -LiteralPath $path).Path
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$directoryInfo = [System.IO.DirectoryInfo]::new($resolved)
$acl = $directoryInfo.GetAccessControl()
$acl.SetAccessRuleProtection($true, $false)
foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleAll($rule) }
$inheritance = 'ContainerInherit,ObjectInherit'
$rule = New-Object Security.AccessControl.FileSystemAccessRule(
    $sid, 'FullControl', $inheritance, 'None', 'Allow'
)
[void]$acl.AddAccessRule($rule)
$acl.SetOwner($sid)
$directoryInfo.SetAccessControl($acl)
$verified = $directoryInfo.GetAccessControl()
$ownerSid = $verified.GetOwner([Security.Principal.SecurityIdentifier])
$rules = @($verified.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
$fullControl = [Security.AccessControl.FileSystemRights]::FullControl
$current = @($rules | Where-Object {
    $_.IdentityReference -eq $sid -and $_.AccessControlType -eq 'Allow' -and
    (($_.FileSystemRights -band $fullControl) -eq $fullControl)
})
$other = @($rules | Where-Object { $_.IdentityReference -ne $sid })
$valid = $verified.AreAccessRulesProtected -and $ownerSid -eq $sid
$valid = $valid -and $current.Count -eq 1 -and $other.Count -eq 0
$result = [pscustomobject]@{
    valid = $valid
    canonical_path = $resolved
    current_sid = $sid.Value
    owner_sid = $ownerSid.Value
    dacl_protected = $verified.AreAccessRulesProtected
    current_full_control_rules = $current.Count
    other_access_rules = $other.Count
}
$result | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    try:
        verification = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PermissionError("unable to validate bootstrap credential directory ACL") from error
    if (
        result.returncode != 0
        or not isinstance(verification, dict)
        or verification.get("canonical_path") != str(directory.resolve())
        or verification.get("valid") is not True
        or not isinstance(verification.get("current_sid"), str)
        or not verification["current_sid"]
        or verification.get("owner_sid") != verification["current_sid"]
        or verification.get("dacl_protected") is not True
        or verification.get("current_full_control_rules") != 1
        or verification.get("other_access_rules") != 0
    ):
        raise PermissionError("unable to restrict bootstrap credential directory ACL")


async def bootstrap(credentials_file: Path, database_url: str) -> int:
    """Atomically create missing approved admins and hand off only their passwords."""
    if credentials_file.exists():
        raise FileExistsError(f"credentials file already exists: {credentials_file}")
    database = Database(database_url)
    created_file = False
    try:
        passwords = shared_password_service()
        async with database.transaction() as session:
            users = UserRepository(session)
            pending: list[tuple[str, str]] = []
            for email in APPROVED_ADMINS:
                if await users.get_by_email(email) is None:
                    password = generate_password()
                    pending.append((email, password))
                    await users.create(
                        email=email,
                        display_name=email.split("@", maxsplit=1)[0],
                        password_hash=await passwords.hash_async(password),
                        roles=["admin"],
                        force_password_change=True,
                    )
            if pending:
                write_credentials_once(credentials_file, pending)
                created_file = True
        return len(pending)
    except BaseException:
        if created_file:
            credentials_file.unlink(missing_ok=True)
        raise
    finally:
        await database.close()


def parse_args() -> argparse.Namespace:
    """Parse operational arguments without resolving required runtime secrets."""
    parser = argparse.ArgumentParser(
        description="Bootstrap approved Project Recovery administrators."
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=DEFAULT_CREDENTIALS_FILE,
        help="exclusive local credential handoff path",
    )
    return parser.parse_args()


def main() -> int:
    """Run the bootstrap and report only a non-sensitive completion count."""
    args = parse_args()
    settings = Settings()
    created = asyncio.run(
        bootstrap(args.credentials_file, settings.database_url.get_secret_value())
    )
    print(f"Bootstrap complete: {created} administrator account(s) created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
