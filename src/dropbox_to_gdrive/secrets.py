"""Load credentials from environment variables or AWS Secrets Manager."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from dropbox_to_gdrive.config import Config, DropboxCredentials, GoogleCredentials, ResolvedSecrets

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def _load_secret_json(arn: str, region: str) -> dict[str, Any]:
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=arn)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise ValueError(f"Secret {arn} has no SecretString payload")
    payload = json.loads(secret_string)
    if not isinstance(payload, dict):
        raise ValueError(f"Secret {arn} must be a JSON object")
    return payload


def _optional_key(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return None


def _require_key(data: dict[str, Any], *keys: str) -> str:
    value = _optional_key(data, *keys)
    if value:
        return value
    raise ValueError(f"Missing required secret key (expected one of: {', '.join(keys)})")


def _google_from_mapping(data: dict[str, Any]) -> GoogleCredentials:
    return GoogleCredentials(
        client_id=_require_key(data, "google_client_id", "GOOGLE_CLIENT_ID"),
        client_secret=_require_key(data, "google_client_secret", "GOOGLE_CLIENT_SECRET"),
        refresh_token=_require_key(data, "google_refresh_token", "GOOGLE_REFRESH_TOKEN"),
        token_uri=data.get("google_token_uri", "https://oauth2.googleapis.com/token"),
    )


def _dropbox_from_mapping(data: dict[str, Any]) -> DropboxCredentials:
    refresh_token = _optional_key(data, "dropbox_refresh_token", "DROPBOX_REFRESH_TOKEN")
    app_key = _optional_key(data, "dropbox_app_key", "DROPBOX_APP_KEY")
    app_secret = _optional_key(data, "dropbox_app_secret", "DROPBOX_APP_SECRET")
    access_token = _optional_key(data, "dropbox_access_token", "DROPBOX_ACCESS_TOKEN")

    if refresh_token and app_key and app_secret:
        return DropboxCredentials(
            app_key=app_key,
            app_secret=app_secret,
            refresh_token=refresh_token,
            access_token=access_token,
        )
    if access_token:
        return DropboxCredentials(access_token=access_token)
    raise ValueError(
        "Missing Dropbox credentials. Provide dropbox_refresh_token + dropbox_app_key + "
        "dropbox_app_secret, or dropbox_access_token."
    )


def _dropbox_from_env() -> DropboxCredentials:
    refresh_token = _optional_env("DROPBOX_REFRESH_TOKEN")
    app_key = _optional_env("DROPBOX_APP_KEY")
    app_secret = _optional_env("DROPBOX_APP_SECRET")
    access_token = _optional_env("DROPBOX_ACCESS_TOKEN")

    if refresh_token and app_key and app_secret:
        return DropboxCredentials(
            app_key=app_key,
            app_secret=app_secret,
            refresh_token=refresh_token,
            access_token=access_token,
        )
    if access_token:
        return DropboxCredentials(access_token=access_token)
    raise ValueError(
        "Set DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET "
        "or DROPBOX_ACCESS_TOKEN"
    )


def _google_from_env() -> GoogleCredentials:
    return GoogleCredentials(
        client_id=_require_env("GOOGLE_CLIENT_ID"),
        client_secret=_require_env("GOOGLE_CLIENT_SECRET"),
        refresh_token=_require_env("GOOGLE_REFRESH_TOKEN"),
        token_uri=os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
    )


def resolve_secrets(config: Config) -> ResolvedSecrets:
    """Resolve Dropbox and Google credentials from env or Secrets Manager."""

    if config.secrets_manager_arn:
        logger.info("Loading credentials from Secrets Manager: %s", config.secrets_manager_arn)
        payload = _load_secret_json(config.secrets_manager_arn, config.aws_region)
        dropbox = _dropbox_from_mapping(payload)
        google = _google_from_mapping(payload)
        known = {
            "dropbox_access_token",
            "DROPBOX_ACCESS_TOKEN",
            "dropbox_refresh_token",
            "DROPBOX_REFRESH_TOKEN",
            "dropbox_app_key",
            "DROPBOX_APP_KEY",
            "dropbox_app_secret",
            "DROPBOX_APP_SECRET",
            "google_client_id",
            "GOOGLE_CLIENT_ID",
            "google_client_secret",
            "GOOGLE_CLIENT_SECRET",
            "google_refresh_token",
            "GOOGLE_REFRESH_TOKEN",
            "google_token_uri",
        }
        extra = {k: str(v) for k, v in payload.items() if k not in known}
        return ResolvedSecrets(dropbox=dropbox, google=google, extra=extra)

    return ResolvedSecrets(dropbox=_dropbox_from_env(), google=_google_from_env())
