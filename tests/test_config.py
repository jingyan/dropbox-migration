import pytest

from dropbox_to_gdrive.config import Config
from dropbox_to_gdrive.dropbox_client import DropboxClient


def test_config_requires_credentials(monkeypatch):
    for key in (
        "DROPBOX_ACCESS_TOKEN",
        "DROPBOX_REFRESH_TOKEN",
        "DROPBOX_APP_KEY",
        "DROPBOX_APP_SECRET",
        "SECRETS_MANAGER_ARN",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="DROPBOX_REFRESH_TOKEN"):
        Config.from_env()


def test_config_accepts_refresh_token_creds(monkeypatch):
    monkeypatch.delenv("DROPBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SECRETS_MANAGER_ARN", raising=False)
    monkeypatch.setenv("DROPBOX_APP_KEY", "app-key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app-secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "refresh-token")

    config = Config.from_env()
    assert config.dropbox_access_token is None


def test_config_accepts_secrets_manager_arn(monkeypatch):
    for key in ("DROPBOX_ACCESS_TOKEN", "DROPBOX_REFRESH_TOKEN", "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SECRETS_MANAGER_ARN", "arn:aws:secretsmanager:us-east-1:1:secret:x")

    config = Config.from_env()
    assert config.secrets_manager_arn.startswith("arn:aws:secretsmanager")


def test_dropbox_relative_path():
    assert DropboxClient.relative_path("", "/Documents/a.txt") == "Documents/a.txt"
    assert DropboxClient.relative_path("/Photos", "/Photos/2024/a.jpg") == "2024/a.jpg"
    assert DropboxClient.parent_path("/Documents/a.txt") == "/Documents"
