#!/usr/bin/env python3
"""Interactive helper to obtain Google OAuth refresh token for personal Drive."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/oauth_setup.py /path/to/client_secret.json")
        return 2

    client_secret_path = Path(sys.argv[1])
    if not client_secret_path.exists():
        print(f"File not found: {client_secret_path}")
        return 2

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    payload = {
        "google_client_id": creds.client_id,
        "google_client_secret": creds.client_secret,
        "google_refresh_token": creds.refresh_token,
    }
    print("\nAdd these to your .env or AWS Secrets Manager JSON:\n")
    print(json.dumps(payload, indent=2))
    print(
        "\nDropbox: create an app at https://www.dropbox.com/developers/apps "
        "and generate an access token with files.metadata.read + files.content.read scopes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
