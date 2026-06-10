#!/usr/bin/env bash
set -euo pipefail

# Sync project to oracle-2.
#
# Usage:
#   ./deploy/rsync_to_remote.sh
#
# Override defaults:
#   LOCAL_PATH=/other/path REMOTE_HOST=my-host REMOTE_PATH=/remote/path ./deploy/rsync_to_remote.sh

LOCAL_PATH="${LOCAL_PATH:-/Users/jingy/code/dropbox-migration}"
REMOTE_HOST="${REMOTE_HOST:-oracle-2}"
REMOTE_PATH="${REMOTE_PATH:-/home/opc/dropbox-migration/}"

echo "Syncing ${LOCAL_PATH}/ -> ${REMOTE_HOST}:${REMOTE_PATH}"

rsync -avz \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.env' \
  "${LOCAL_PATH}/" "${REMOTE_HOST}:${REMOTE_PATH}"

echo "Done."
