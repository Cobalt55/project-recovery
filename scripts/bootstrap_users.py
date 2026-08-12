"""Create the approved local administrators exactly once."""

import argparse
import asyncio
import os
import secrets
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from project_recovery.auth.passwords import PasswordService  # noqa: E402
from project_recovery.config import Settings  # noqa: E402
from project_recovery.db import Database  # noqa: E402
from project_recovery.repositories.users import UserRepository  # noqa: E402

APPROVED_ADMINS = ("pricejfl@gmail.com", "alecmusheno@gmail.com")
DEFAULT_CREDENTIALS_FILE = Path("local-secrets/bootstrap-credentials.txt")


def generate_password() -> str:
    """Return an independently random password with at least 20 characters."""
    return secrets.token_urlsafe(24)


def write_credentials_once(path: Path, credentials: Iterable[tuple[str, str]]) -> None:
    """Exclusively create the local credential handoff without console output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write("Bootstrap administrator credentials\n\n")
        for email, password in credentials:
            output.write(f"{email}: {password}\n")
    if os.name != "nt":
        path.chmod(0o600)


async def bootstrap(credentials_file: Path, database_url: str) -> int:
    """Atomically create missing approved admins and hand off only their passwords."""
    if credentials_file.exists():
        raise FileExistsError(f"credentials file already exists: {credentials_file}")
    database = Database(database_url)
    created_file = False
    try:
        passwords = PasswordService()
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
                        password_hash=passwords.hash(password),
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
