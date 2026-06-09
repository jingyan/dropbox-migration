"""Checkpoint storage for resumable migrations."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3

logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    files_discovered: int = 0
    files_migrated: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_migrated: int = 0


@dataclass
class Checkpoint:
    version: int = 2
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    dropbox_root_path: str | None = None
    gdrive_root_folder_id: str | None = None
    file_manifest: dict[str, dict[str, object]] = field(default_factory=dict)
    completed_paths: set[str] = field(default_factory=set)
    failed_paths: dict[str, str] = field(default_factory=dict)
    stats: MigrationStats = field(default_factory=MigrationStats)

    def mark_completed(self, path: str, size: int) -> None:
        self.completed_paths.add(path)
        self.failed_paths.pop(path, None)
        self.stats.files_migrated += 1
        self.stats.bytes_migrated += size
        self.updated_at = datetime.now(UTC).isoformat()

    def mark_failed(self, path: str, error: str) -> None:
        self.failed_paths[path] = error
        self.stats.files_failed += 1
        self.updated_at = datetime.now(UTC).isoformat()

    def mark_skipped(self, path: str) -> None:
        self.completed_paths.add(path)
        self.stats.files_skipped += 1
        self.updated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["completed_paths"] = sorted(self.completed_paths)
        payload["file_manifest"] = {
            rel_path: payload["file_manifest"][rel_path]
            for rel_path in sorted(self.file_manifest)
        }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        stats_data = data.get("stats") or {}
        stats = MigrationStats(**stats_data) if isinstance(stats_data, dict) else MigrationStats()
        manifest = data.get("file_manifest") or {}
        if not isinstance(manifest, dict):
            manifest = {}
        return cls(
            version=int(data.get("version", 1)),
            started_at=str(data.get("started_at", datetime.now(UTC).isoformat())),
            updated_at=str(data.get("updated_at", datetime.now(UTC).isoformat())),
            dropbox_root_path=data.get("dropbox_root_path"),
            gdrive_root_folder_id=data.get("gdrive_root_folder_id"),
            file_manifest=dict(manifest),
            completed_paths=set(data.get("completed_paths") or []),
            failed_paths=dict(data.get("failed_paths") or {}),
            stats=stats,
        )


class CheckpointStore:
    """Read/write checkpoint state to local disk or S3."""

    def __init__(self, uri: str, aws_region: str = "us-east-1") -> None:
        self.uri = uri
        self.aws_region = aws_region
        parsed = urlparse(uri)
        self.scheme = parsed.scheme or "file"
        self.bucket = parsed.netloc
        self.key = parsed.path.lstrip("/")

    def load(self) -> Checkpoint:
        if self.scheme == "file":
            path = Path(self.uri.removeprefix("file://"))
            if not path.exists():
                logger.info("No checkpoint found at %s; starting fresh", path)
                return Checkpoint()
            logger.info("Loading checkpoint from %s", path)
            return Checkpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))

        if self.scheme == "s3":
            client = boto3.client("s3", region_name=self.aws_region)
            try:
                response = client.get_object(Bucket=self.bucket, Key=self.key)
                body = response["Body"].read().decode("utf-8")
                logger.info("Loading checkpoint from s3://%s/%s", self.bucket, self.key)
                return Checkpoint.from_dict(json.loads(body))
            except client.exceptions.NoSuchKey:
                logger.info("No checkpoint found at s3://%s/%s; starting fresh", self.bucket, self.key)
                return Checkpoint()

        raise ValueError(f"Unsupported checkpoint URI scheme: {self.scheme}")

    def save(self, checkpoint: Checkpoint) -> None:
        payload = json.dumps(checkpoint.to_dict(), indent=2, sort_keys=True)

        if self.scheme == "file":
            path = Path(self.uri.removeprefix("file://"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            logger.debug("Saved checkpoint to %s", path)
            return

        if self.scheme == "s3":
            client = boto3.client("s3", region_name=self.aws_region)
            client.put_object(
                Bucket=self.bucket,
                Key=self.key,
                Body=payload.encode("utf-8"),
                ContentType="application/json",
            )
            logger.debug("Saved checkpoint to s3://%s/%s", self.bucket, self.key)
            return

        raise ValueError(f"Unsupported checkpoint URI scheme: {self.scheme}")
