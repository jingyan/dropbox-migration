"""Checkpoint storage for resumable migrations."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import boto3

logger = logging.getLogger(__name__)

CheckpointPart = Literal["state", "manifest", "folders"]
ALL_CHECKPOINT_PARTS: frozenset[CheckpointPart] = frozenset({"state", "manifest", "folders"})


@dataclass
class MigrationStats:
    files_discovered: int = 0
    files_migrated: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    bytes_migrated: int = 0


@dataclass
class Checkpoint:
    version: int = 3
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    dropbox_root_path: str | None = None
    gdrive_root_folder_id: str | None = None
    file_manifest: dict[str, dict[str, object]] = field(default_factory=dict)
    folder_map: dict[str, str] = field(default_factory=dict)
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

    def to_state_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "dropbox_root_path": self.dropbox_root_path,
            "gdrive_root_folder_id": self.gdrive_root_folder_id,
            "completed_paths": sorted(self.completed_paths),
            "failed_paths": self.failed_paths,
            "stats": asdict(self.stats),
        }

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "files": {
                rel_path: self.file_manifest[rel_path]
                for rel_path in sorted(self.file_manifest)
            },
        }

    def to_folders_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "folders": {
                folder_path: self.folder_map[folder_path]
                for folder_path in sorted(self.folder_map)
            },
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_state_dict()
        payload["file_manifest"] = self.to_manifest_dict()["files"]
        payload["folder_map"] = self.to_folders_dict()["folders"]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        stats_data = data.get("stats") or {}
        stats = MigrationStats(**stats_data) if isinstance(stats_data, dict) else MigrationStats()
        manifest = data.get("file_manifest") or data.get("files") or {}
        if not isinstance(manifest, dict):
            manifest = {}
        folder_map = data.get("folder_map") or data.get("folders") or {}
        if not isinstance(folder_map, dict):
            folder_map = {}
        return cls(
            version=int(data.get("version", 1)),
            started_at=str(data.get("started_at", datetime.now(UTC).isoformat())),
            updated_at=str(data.get("updated_at", datetime.now(UTC).isoformat())),
            dropbox_root_path=data.get("dropbox_root_path"),
            gdrive_root_folder_id=data.get("gdrive_root_folder_id"),
            file_manifest=dict(manifest),
            folder_map={str(k): str(v) for k, v in folder_map.items()},
            completed_paths=set(data.get("completed_paths") or []),
            failed_paths=dict(data.get("failed_paths") or {}),
            stats=stats,
        )


class CheckpointStore:
    """Read/write checkpoint state split across multiple files."""

    def __init__(self, uri: str, aws_region: str = "us-east-1") -> None:
        self.uri = uri
        self.aws_region = aws_region
        parsed = urlparse(uri)
        self.scheme = parsed.scheme or "file"
        self.bucket = parsed.netloc
        self.key = parsed.path.lstrip("/")

    @property
    def manifest_uri(self) -> str:
        return self._companion_uri(".manifest")

    @property
    def folders_uri(self) -> str:
        return self._companion_uri(".folders")

    def _companion_uri(self, suffix: str) -> str:
        if self.uri.endswith(".json"):
            return f"{self.uri[:-5]}{suffix}.json"
        return f"{self.uri.rstrip('/')}{suffix}.json"

    def load(self) -> Checkpoint:
        state_data = self._read_json(self.uri)
        if state_data is None:
            logger.info("No checkpoint found at %s; starting fresh", self.uri)
            return Checkpoint()

        manifest_data = self._read_json(self.manifest_uri)
        folders_data = self._read_json(self.folders_uri)

        merged = dict(state_data)
        if manifest_data is not None:
            merged["file_manifest"] = manifest_data.get("files", {})
            logger.info("Loaded file manifest from %s", self.manifest_uri)
        elif state_data.get("file_manifest"):
            merged["file_manifest"] = state_data["file_manifest"]
            logger.info("Loaded file manifest from legacy monolithic checkpoint")

        if folders_data is not None:
            merged["folder_map"] = folders_data.get("folders", {})
            logger.info("Loaded folder map from %s", self.folders_uri)
        elif state_data.get("folder_map"):
            merged["folder_map"] = state_data["folder_map"]
            logger.info("Loaded folder map from legacy monolithic checkpoint")

        logger.info("Loaded checkpoint state from %s", self.uri)
        return Checkpoint.from_dict(merged)

    def save(
        self,
        checkpoint: Checkpoint,
        parts: frozenset[CheckpointPart] | None = None,
    ) -> None:
        targets = parts or ALL_CHECKPOINT_PARTS
        if "state" in targets:
            self._write_json(self.uri, checkpoint.to_state_dict())
            logger.debug("Saved checkpoint state to %s", self.uri)
        if "manifest" in targets:
            self._write_json(self.manifest_uri, checkpoint.to_manifest_dict())
            logger.debug("Saved file manifest to %s", self.manifest_uri)
        if "folders" in targets:
            self._write_json(self.folders_uri, checkpoint.to_folders_dict())
            logger.debug("Saved folder map to %s", self.folders_uri)

    def _read_json(self, uri: str) -> dict[str, Any] | None:
        if self.scheme == "file":
            path = Path(uri.removeprefix("file://"))
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None

        if self.scheme == "s3":
            bucket, key = self._parse_s3_uri(uri)
            client = boto3.client("s3", region_name=self.aws_region)
            try:
                response = client.get_object(Bucket=bucket, Key=key)
                payload = json.loads(response["Body"].read().decode("utf-8"))
                return payload if isinstance(payload, dict) else None
            except client.exceptions.NoSuchKey:
                return None

        raise ValueError(f"Unsupported checkpoint URI scheme: {self.scheme}")

    def _write_json(self, uri: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True)
        if self.scheme == "file":
            path = Path(uri.removeprefix("file://"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            return

        if self.scheme == "s3":
            bucket, key = self._parse_s3_uri(uri)
            client = boto3.client("s3", region_name=self.aws_region)
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
            )
            return

        raise ValueError(f"Unsupported checkpoint URI scheme: {self.scheme}")

    def _parse_s3_uri(self, uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        return parsed.netloc, parsed.path.lstrip("/")
