"""Dropbox API wrapper for listing and downloading files."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import FileMetadata, FolderMetadata
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from dropbox_to_gdrive.config import DropboxCredentials

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DropboxFile:
    path: str
    name: str
    size: int
    content_hash: str | None
    server_modified: str | None


class DropboxClient:
    """Thin wrapper around the Dropbox SDK."""

    def __init__(self, creds: DropboxCredentials) -> None:
        if creds.uses_refresh_token():
            logger.info("Using Dropbox refresh token (auto-refreshes on expiry)")
            self._dbx = dropbox.Dropbox(
                oauth2_refresh_token=creds.refresh_token,
                app_key=creds.app_key,
                app_secret=creds.app_secret,
                timeout=120,
            )
        elif creds.access_token:
            logger.warning(
                "Using short-lived Dropbox access token; set DROPBOX_REFRESH_TOKEN for long migrations"
            )
            self._dbx = dropbox.Dropbox(
                oauth2_access_token=creds.access_token,
                timeout=120,
            )
        else:
            raise ValueError(
                "Dropbox credentials incomplete. Set DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + "
                "DROPBOX_APP_SECRET, or DROPBOX_ACCESS_TOKEN."
            )

    def verify_connection(self) -> str:
        account = self._dbx.users_get_current_account()
        return account.email

    def iter_files(self, root_path: str = "") -> Iterator[DropboxFile]:
        """Recursively yield all files under root_path."""

        normalized_root = self._normalize_folder_path(root_path)
        logger.info("Listing Dropbox files under %r", normalized_root or "/")

        for entry in self._walk(normalized_root):
            if isinstance(entry, FileMetadata):
                yield DropboxFile(
                    path=entry.path_display or entry.path_lower or entry.name,
                    name=entry.name,
                    size=entry.size,
                    content_hash=entry.content_hash,
                    server_modified=(
                        entry.server_modified.isoformat() if entry.server_modified else None
                    ),
                )

    @retry(
        retry=retry_if_exception_type((ApiError, TimeoutError, OSError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def download(self, path: str, chunk_size: int = 8 * 1024 * 1024) -> Iterator[bytes]:
        """Stream file content in chunks."""

        _, response = self._dbx.files_download(path)
        stream = response.raw
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def _walk(self, folder_path: str) -> Iterator[FileMetadata | FolderMetadata]:
        cursor: str | None = None
        while True:
            if cursor is None:
                result = self._dbx.files_list_folder(folder_path, recursive=True)
            else:
                result = self._dbx.files_list_folder_continue(cursor)

            for entry in result.entries:
                yield entry

            if not result.has_more:
                break
            cursor = result.cursor

    @staticmethod
    def _normalize_folder_path(path: str) -> str:
        cleaned = path.strip()
        if not cleaned or cleaned == "/":
            return ""
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned.rstrip("/")

    @staticmethod
    def parent_path(path: str) -> str:
        if "/" not in path.strip("/"):
            return ""
        return path.rsplit("/", 1)[0]

    @staticmethod
    def relative_path(root_path: str, file_path: str) -> str:
        root = DropboxClient._normalize_folder_path(root_path)
        if not root:
            return file_path.lstrip("/")
        prefix = root if root.endswith("/") else f"{root}/"
        if file_path.startswith(prefix):
            return file_path[len(prefix) :]
        return file_path.lstrip("/")
