"""Google Drive API wrapper for folder creation and file uploads."""

from __future__ import annotations

import io
import json
import logging
import os
from typing import Any, Iterator

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from dropbox_to_gdrive.config import GoogleCredentials
from dropbox_to_gdrive.proxy import (
    apply_proxy_to_session,
    build_refresh_request,
    log_proxy_usage,
    resolve_proxy_url,
)

logger = logging.getLogger(__name__)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
DEFAULT_HTTP_TIMEOUT = 60


def _is_retryable_request_error(exc: BaseException) -> bool:
    if isinstance(exc, requests.Timeout):
        return True
    if isinstance(exc, requests.ConnectionError):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


class GoogleDriveClient:
    """Google Drive client using OAuth refresh tokens and requests (proxy-friendly)."""

    def __init__(self, creds: GoogleCredentials) -> None:
        self._google_creds = creds
        self._proxy_url = resolve_proxy_url()
        self._timeout = int(os.environ.get("GOOGLE_HTTP_TIMEOUT", str(DEFAULT_HTTP_TIMEOUT)))
        log_proxy_usage(self._proxy_url)

        credentials = Credentials(
            token=None,
            refresh_token=creds.refresh_token,
            token_uri=creds.token_uri,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            scopes=[DRIVE_SCOPE],
        )
        refresh_request = build_refresh_request(self._proxy_url)
        try:
            credentials.refresh(refresh_request)
        except requests.RequestException as exc:
            raise ConnectionError(
                "Could not reach Google OAuth (oauth2.googleapis.com). "
                "Check HTTPS_PROXY/GOOGLE_PROXY and ensure the proxy is running."
            ) from exc

        self._session = AuthorizedSession(credentials, auth_request=refresh_request)
        apply_proxy_to_session(self._session, self._proxy_url)

    def verify_connection(self) -> str:
        try:
            response = self._session.get(
                f"{DRIVE_API_BASE}/about",
                params={"fields": "user(emailAddress)"},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ConnectionError(
                "Could not reach Google Drive API (www.googleapis.com). "
                "Your proxy works in curl but Python must use HTTPS_PROXY or GOOGLE_PROXY in .env. "
                "For SOCKS proxies use socks5h://127.0.0.1:7891"
            ) from exc
        return response.json()["user"]["emailAddress"]

    @retry(
        retry=retry_if_exception(_is_retryable_request_error),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def ensure_folder(self, name: str, parent_id: str) -> str:
        """Return folder ID, creating it under parent_id if needed."""

        query = (
            "mimeType='application/vnd.google-apps.folder' "
            f"and name='{self._escape_query(name)}' "
            f"and '{parent_id}' in parents and trashed=false"
        )
        response = self._session.get(
            f"{DRIVE_API_BASE}/files",
            params={"q": query, "spaces": "drive", "fields": "files(id,name)", "pageSize": 1},
            timeout=self._timeout,
        )
        response.raise_for_status()
        files = response.json().get("files", [])
        if files:
            return files[0]["id"]

        created = self._session.post(
            f"{DRIVE_API_BASE}/files",
            params={"fields": "id"},
            json={
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            },
            timeout=self._timeout,
        )
        created.raise_for_status()
        folder_id = created.json()["id"]
        logger.debug("Created Drive folder %r (%s)", name, folder_id)
        return folder_id

    @retry(
        retry=retry_if_exception(_is_retryable_request_error),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def find_file(self, name: str, parent_id: str) -> str | None:
        query = (
            f"name='{self._escape_query(name)}' "
            f"and '{parent_id}' in parents and trashed=false"
        )
        response = self._session.get(
            f"{DRIVE_API_BASE}/files",
            params={
                "q": query,
                "spaces": "drive",
                "fields": "files(id,name,size,md5Checksum)",
                "pageSize": 1,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        files = response.json().get("files", [])
        if files:
            return files[0]["id"]
        return None

    @retry(
        retry=retry_if_exception(_is_retryable_request_error),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def upload_stream(
        self,
        name: str,
        parent_id: str,
        size: int,
        stream: Iterator[bytes],
        mime_type: str = "application/octet-stream",
    ) -> str:
        """Upload file content from a chunk iterator."""

        buffer = io.BytesIO()
        for chunk in stream:
            buffer.write(chunk)
        buffer.seek(0)

        metadata: dict[str, Any] = {"name": name, "parents": [parent_id]}
        response = self._session.post(
            f"{DRIVE_UPLOAD_BASE}/files",
            params={"uploadType": "multipart", "fields": "id,size"},
            files={
                "metadata": ("metadata", json.dumps(metadata), "application/json; charset=UTF-8"),
                "file": (name, buffer.getvalue(), mime_type),
            },
            timeout=max(self._timeout, 300),
        )
        response.raise_for_status()
        file_id = response.json()["id"]
        logger.debug("Uploaded %r (%s bytes) -> %s", name, size, file_id)
        return file_id

    @staticmethod
    def _escape_query(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")
