#!/bin/sh
set -eu

command="${1:-migrate}"

if [ "$command" = "migrate" ]; then
  echo "Starting migration (will not exit until finished)..."
  exec dropbox-to-gdrive migrate
fi

exec dropbox-to-gdrive "$@"
