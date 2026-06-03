"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from dropbox_to_gdrive import __version__
from dropbox_to_gdrive.checkpoint import CheckpointStore
from dropbox_to_gdrive.config import Config
from dropbox_to_gdrive.dropbox_client import DropboxClient
from dropbox_to_gdrive.gdrive_client import GoogleDriveClient
from dropbox_to_gdrive.migrator import Migrator
from dropbox_to_gdrive.secrets import resolve_secrets


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate files from Dropbox personal account to Google Drive personal account.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "command",
        choices=["migrate", "verify"],
        help="migrate: run migration; verify: test API credentials",
    )
    return parser


def _load_dotenv() -> None:
    """Load .env from the current directory or project root if present."""

    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            return


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    _configure_logging(config.log_level)

    try:
        secrets = resolve_secrets(config)
    except ValueError as exc:
        print(f"Credential error: {exc}", file=sys.stderr)
        return 2

    dropbox_client = DropboxClient(secrets.dropbox)

    if args.command == "verify":
        try:
            dropbox_email = dropbox_client.verify_connection()
            print(f"Dropbox account: {dropbox_email}")
        except Exception as exc:  # noqa: BLE001 - surface API errors to the user
            print(f"Dropbox verification failed: {exc}", file=sys.stderr)
            return 1

        try:
            gdrive_client = GoogleDriveClient(secrets.google)
            gdrive_email = gdrive_client.verify_connection()
            print(f"Google Drive account: {gdrive_email}")
        except ConnectionError as exc:
            print(f"Google Drive verification failed: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - surface API errors to the user
            print(f"Google Drive verification failed: {exc}", file=sys.stderr)
            return 1
        return 0

    gdrive_client = GoogleDriveClient(secrets.google)
    checkpoint_store = CheckpointStore(config.checkpoint_uri, aws_region=config.aws_region)
    migrator = Migrator(
        config=config,
        dropbox_client=dropbox_client,
        gdrive_client=gdrive_client,
        checkpoint_store=checkpoint_store,
    )
    result = migrator.run()
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
