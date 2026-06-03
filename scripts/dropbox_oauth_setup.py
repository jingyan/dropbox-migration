#!/usr/bin/env python3
"""Obtain a Dropbox OAuth refresh token for long-running migrations."""

from __future__ import annotations

import json
import os
import sys

from dropbox import DropboxOAuth2FlowNoRedirect


def main() -> int:
    app_key = os.environ.get("DROPBOX_APP_KEY") or (len(sys.argv) > 1 and sys.argv[1])
    app_secret = os.environ.get("DROPBOX_APP_SECRET") or (len(sys.argv) > 2 and sys.argv[2])

    if not app_key or not app_secret:
        print(
            "Usage: DROPBOX_APP_KEY=... DROPBOX_APP_SECRET=... python scripts/dropbox_oauth_setup.py\n"
            "   or: python scripts/dropbox_oauth_setup.py <app_key> <app_secret>"
        )
        return 2

    auth_flow = DropboxOAuth2FlowNoRedirect(
        app_key,
        app_secret,
        token_access_type="offline",
    )
    authorize_url = auth_flow.start()
    print("1. Open this URL in your browser:\n")
    print(authorize_url)
    print('\n2. Click "Allow", then copy the authorization code.')
    auth_code = input("\n3. Paste the authorization code here: ").strip()
    oauth_result = auth_flow.finish(auth_code)

    payload = {
        "DROPBOX_APP_KEY": app_key,
        "DROPBOX_APP_SECRET": app_secret,
        "DROPBOX_REFRESH_TOKEN": oauth_result.refresh_token,
    }
    print("\nAdd these to your .env:\n")
    print(json.dumps(payload, indent=2))
    print(
        "\nYou can remove DROPBOX_ACCESS_TOKEN — the refresh token replaces it for long migrations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
