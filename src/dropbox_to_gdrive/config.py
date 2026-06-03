"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the migration job."""

    dropbox_access_token: str | None = None
    dropbox_root_path: str = ""
    gdrive_root_folder_id: str = "root"
    gdrive_root_folder_name: str = "Dropbox Migration"
    checkpoint_uri: str = "file:///tmp/checkpoint.json"
    dry_run: bool = False
    max_retries: int = 5
    chunk_size_mb: int = 8
    aws_region: str = "us-east-1"
    secrets_manager_arn: str | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        secrets_manager_arn = _env("SECRETS_MANAGER_ARN")
        token = _env("DROPBOX_ACCESS_TOKEN")
        refresh = _env("DROPBOX_REFRESH_TOKEN")
        app_key = _env("DROPBOX_APP_KEY")
        app_secret = _env("DROPBOX_APP_SECRET")
        has_refresh_creds = refresh and app_key and app_secret
        if not token and not has_refresh_creds and not secrets_manager_arn:
            raise ValueError(
                "Set DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET, "
                "DROPBOX_ACCESS_TOKEN, or SECRETS_MANAGER_ARN"
            )

        return cls(
            dropbox_access_token=token,
            dropbox_root_path=_env("DROPBOX_ROOT_PATH", "") or "",
            gdrive_root_folder_id=_env("GDRIVE_ROOT_FOLDER_ID", "root") or "root",
            gdrive_root_folder_name=_env("GDRIVE_ROOT_FOLDER_NAME", "Dropbox Migration")
            or "Dropbox Migration",
            checkpoint_uri=_env("CHECKPOINT_URI", "file:///tmp/checkpoint.json")
            or "file:///tmp/checkpoint.json",
            dry_run=_env_bool("DRY_RUN"),
            max_retries=int(_env("MAX_RETRIES", "5") or "5"),
            chunk_size_mb=int(_env("CHUNK_SIZE_MB", "8") or "8"),
            aws_region=_env("AWS_REGION", "us-east-1") or "us-east-1",
            secrets_manager_arn=secrets_manager_arn,
            log_level=_env("LOG_LEVEL", "INFO") or "INFO",
        )


@dataclass
class DropboxCredentials:
    """Dropbox OAuth credentials for a personal account."""

    app_key: str | None = None
    app_secret: str | None = None
    refresh_token: str | None = None
    access_token: str | None = None

    def uses_refresh_token(self) -> bool:
        return bool(self.refresh_token and self.app_key and self.app_secret)


@dataclass
class GoogleCredentials:
    """Google OAuth credentials for a personal Drive account."""

    client_id: str
    client_secret: str
    refresh_token: str
    token_uri: str = "https://oauth2.googleapis.com/token"


@dataclass
class ResolvedSecrets:
    """Secrets resolved from env vars or AWS Secrets Manager."""

    dropbox: DropboxCredentials
    google: GoogleCredentials
    extra: dict[str, str] = field(default_factory=dict)
