#!/usr/bin/env python3
"""Submit an on-demand AWS Batch migration job."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import boto3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit Dropbox-to-GDrive AWS Batch job")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--job-queue", required=True)
    parser.add_argument("--job-definition", required=True)
    parser.add_argument("--job-name", default="dropbox-to-gdrive-migration")
    parser.add_argument("--command", default="migrate", choices=["migrate", "verify"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dropbox-root-path", default="")
    parser.add_argument("--checkpoint-uri")
    parser.add_argument("--secrets-manager-arn")
    parser.add_argument("--container-overrides", help="Raw JSON container overrides")
    return parser


def _environment(
    command: str,
    dry_run: bool,
    dropbox_root_path: str,
    checkpoint_uri: str | None,
    secrets_manager_arn: str | None,
) -> list[dict[str, str]]:
    env: list[dict[str, str]] = [
        {"name": "LOG_LEVEL", "value": "INFO"},
    ]
    if dry_run:
        env.append({"name": "DRY_RUN", "value": "true"})
    if dropbox_root_path:
        env.append({"name": "DROPBOX_ROOT_PATH", "value": dropbox_root_path})
    if checkpoint_uri:
        env.append({"name": "CHECKPOINT_URI", "value": checkpoint_uri})
    if secrets_manager_arn:
        env.append({"name": "SECRETS_MANAGER_ARN", "value": secrets_manager_arn})
    return env


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = boto3.client("batch", region_name=args.region)

    container_overrides: dict[str, Any] = {}
    if args.container_overrides:
        container_overrides = json.loads(args.container_overrides)
    else:
        container_overrides = {
            "command": [args.command],
            "environment": _environment(
                command=args.command,
                dry_run=args.dry_run,
                dropbox_root_path=args.dropbox_root_path,
                checkpoint_uri=args.checkpoint_uri,
                secrets_manager_arn=args.secrets_manager_arn,
            ),
        }

    response = client.submit_job(
        jobName=args.job_name,
        jobQueue=args.job_queue,
        jobDefinition=args.job_definition,
        containerOverrides=container_overrides,
    )
    print(json.dumps(response, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
