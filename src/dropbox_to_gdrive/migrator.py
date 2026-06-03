"""Migration orchestrator."""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass

from dropbox_to_gdrive.checkpoint import Checkpoint, CheckpointStore
from dropbox_to_gdrive.config import Config
from dropbox_to_gdrive.dropbox_client import DropboxClient, DropboxFile
from dropbox_to_gdrive.gdrive_client import GoogleDriveClient

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    checkpoint: Checkpoint
    success: bool


class Migrator:
    """Coordinates listing Dropbox files and uploading them to Google Drive."""

    def __init__(
        self,
        config: Config,
        dropbox_client: DropboxClient,
        gdrive_client: GoogleDriveClient,
        checkpoint_store: CheckpointStore,
    ) -> None:
        self.config = config
        self.dropbox = dropbox_client
        self.gdrive = gdrive_client
        self.checkpoint_store = checkpoint_store
        self._folder_cache: dict[str, str] = {}

    def run(self) -> MigrationResult:
        checkpoint = self.checkpoint_store.load()
        root_folder_id = checkpoint.gdrive_root_folder_id or self._ensure_root_folder()
        checkpoint.gdrive_root_folder_id = root_folder_id

        files = list(self.dropbox.iter_files(self.config.dropbox_root_path))
        checkpoint.stats.files_discovered = len(files)
        logger.info("Discovered %d Dropbox files", len(files))

        for index, file_entry in enumerate(files, start=1):
            rel_path = DropboxClient.relative_path(self.config.dropbox_root_path, file_entry.path)
            if rel_path in checkpoint.completed_paths:
                logger.debug("Skipping already migrated file: %s", rel_path)
                continue

            logger.info("[%d/%d] Migrating %s (%d bytes)", index, len(files), rel_path, file_entry.size)
            try:
                self._migrate_file(file_entry, rel_path, root_folder_id, checkpoint)
            except Exception as exc:  # noqa: BLE001 - record per-file failures and continue
                logger.exception("Failed to migrate %s", rel_path)
                checkpoint.mark_failed(rel_path, str(exc))
                self.checkpoint_store.save(checkpoint)

        self.checkpoint_store.save(checkpoint)
        success = checkpoint.stats.files_failed == 0
        logger.info(
            "Migration finished: migrated=%d skipped=%d failed=%d bytes=%d",
            checkpoint.stats.files_migrated,
            checkpoint.stats.files_skipped,
            checkpoint.stats.files_failed,
            checkpoint.stats.bytes_migrated,
        )
        return MigrationResult(checkpoint=checkpoint, success=success)

    def _ensure_root_folder(self) -> str:
        if self.config.gdrive_root_folder_id != "root":
            return self.config.gdrive_root_folder_id
        return self.gdrive.ensure_folder(self.config.gdrive_root_folder_name, "root")

    def _migrate_file(
        self,
        file_entry: DropboxFile,
        rel_path: str,
        root_folder_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        parent_id = self._ensure_parent_folders(rel_path, root_folder_id)

        if self.config.dry_run:
            logger.info("DRY RUN: would upload %s to folder %s", file_entry.name, parent_id)
            checkpoint.mark_skipped(rel_path)
            self.checkpoint_store.save(checkpoint)
            return

        existing_id = self.gdrive.find_file(file_entry.name, parent_id)
        if existing_id:
            logger.info("File already exists in Drive, skipping: %s", rel_path)
            checkpoint.mark_skipped(rel_path)
            self.checkpoint_store.save(checkpoint)
            return

        mime_type, _ = mimetypes.guess_type(file_entry.name)
        mime_type = mime_type or "application/octet-stream"
        chunk_size = self.config.chunk_size_mb * 1024 * 1024
        stream = self.dropbox.download(file_entry.path, chunk_size=chunk_size)
        self.gdrive.upload_stream(
            name=file_entry.name,
            parent_id=parent_id,
            size=file_entry.size,
            stream=stream,
            mime_type=mime_type,
        )
        checkpoint.mark_completed(rel_path, file_entry.size)
        self.checkpoint_store.save(checkpoint)

    def _ensure_parent_folders(self, rel_path: str, root_folder_id: str) -> str:
        parts = rel_path.split("/")
        if len(parts) == 1:
            return root_folder_id

        current_parent = root_folder_id
        current_key = ""
        for part in parts[:-1]:
            current_key = f"{current_key}/{part}" if current_key else part
            cached = self._folder_cache.get(current_key)
            if cached:
                current_parent = cached
                continue
            current_parent = self.gdrive.ensure_folder(part, current_parent)
            self._folder_cache[current_key] = current_parent
        return current_parent
