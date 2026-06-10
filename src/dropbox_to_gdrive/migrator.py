"""Migration orchestrator."""

from __future__ import annotations

import logging
import mimetypes
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime

from dropbox_to_gdrive.checkpoint import Checkpoint, CheckpointStore
from dropbox_to_gdrive.config import Config, ResolvedSecrets
from dropbox_to_gdrive.dropbox_client import DropboxClient, DropboxFile
from dropbox_to_gdrive.gdrive_client import GoogleDriveClient
from dropbox_to_gdrive.progress import MigrationProgressTracker

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    checkpoint: Checkpoint
    success: bool


@dataclass(frozen=True)
class _FileTask:
    file_entry: DropboxFile
    rel_path: str
    parent_id: str


def collect_folder_paths(rel_paths: list[str]) -> list[str]:
    """Return unique folder paths sorted so parents are created before children."""

    folders: set[str] = set()
    for rel_path in rel_paths:
        parts = rel_path.split("/")
        for index in range(1, len(parts)):
            folders.add("/".join(parts[:index]))
    return sorted(folders, key=lambda path: (path.count("/"), path))


class Migrator:
    """Coordinates listing Dropbox files and uploading them to Google Drive."""

    def __init__(
        self,
        config: Config,
        secrets: ResolvedSecrets,
        checkpoint_store: CheckpointStore,
        dropbox_client: DropboxClient | None = None,
        gdrive_client: GoogleDriveClient | None = None,
    ) -> None:
        self.config = config
        self.secrets = secrets
        self.checkpoint_store = checkpoint_store
        self.dropbox = dropbox_client or DropboxClient(secrets.dropbox)
        self.gdrive = gdrive_client or GoogleDriveClient(secrets.google)
        self._folder_cache: dict[str, str] = {}
        self._checkpoint_lock = threading.Lock()

    def run(self) -> MigrationResult:
        checkpoint = self.checkpoint_store.load()
        root_folder_id = checkpoint.gdrive_root_folder_id or self._ensure_root_folder()
        checkpoint.gdrive_root_folder_id = root_folder_id
        self.checkpoint_store.save(checkpoint, parts=frozenset({"state"}))

        files = self._discover_files(checkpoint)
        checkpoint.stats.files_discovered = len(files)
        logger.info("Discovered %d Dropbox files", len(files))

        pending = self._pending_tasks(files, checkpoint)
        if not pending:
            logger.info("No pending files to migrate")
            return MigrationResult(checkpoint=checkpoint, success=checkpoint.stats.files_failed == 0)

        self._prebuild_folder_map([task.rel_path for task in pending], root_folder_id, checkpoint)
        pending = self._attach_parent_ids(pending, root_folder_id)

        progress = MigrationProgressTracker(
            workers=max(1, self.config.workers),
            pending_total=len(pending),
            completed_before=len(checkpoint.completed_paths),
            total_discovered=len(files),
        )
        progress.log_start()

        if self.config.workers <= 1:
            self._run_sequential(pending, checkpoint, progress)
        else:
            self._run_parallel(pending, checkpoint, progress)

        progress.log_summary()
        self.checkpoint_store.save(checkpoint)  # all parts
        success = checkpoint.stats.files_failed == 0
        logger.info(
            "Migration finished: migrated=%d skipped=%d failed=%d bytes=%d",
            checkpoint.stats.files_migrated,
            checkpoint.stats.files_skipped,
            checkpoint.stats.files_failed,
            checkpoint.stats.bytes_migrated,
        )
        return MigrationResult(checkpoint=checkpoint, success=success)

    def _discover_files(self, checkpoint: Checkpoint) -> list[DropboxFile]:
        root_path = self.config.dropbox_root_path
        if (
            not self.config.force_relist
            and checkpoint.file_manifest
            and checkpoint.dropbox_root_path == root_path
        ):
            logger.info(
                "Using cached file manifest (%d files); set FORCE_RELIST=true to rescan Dropbox",
                len(checkpoint.file_manifest),
            )
            return [
                DropboxFile.from_dict(entry)
                for entry in checkpoint.file_manifest.values()
            ]

        logger.info("Scanning Dropbox file list under %r", root_path or "/")
        files = list(self.dropbox.iter_files(root_path))
        checkpoint.dropbox_root_path = root_path
        checkpoint.file_manifest = {
            DropboxClient.relative_path(root_path, file_entry.path): file_entry.to_dict()
            for file_entry in files
        }
        checkpoint.updated_at = datetime.now(UTC).isoformat()
        self.checkpoint_store.save(checkpoint, parts=frozenset({"state", "manifest"}))
        logger.info("Saved file manifest with %d files", len(files))
        return files

    def _pending_tasks(self, files: list[DropboxFile], checkpoint: Checkpoint) -> list[_FileTask]:
        pending: list[_FileTask] = []
        skipped = 0
        for file_entry in files:
            rel_path = DropboxClient.relative_path(self.config.dropbox_root_path, file_entry.path)
            if rel_path in checkpoint.completed_paths:
                skipped += 1
                continue
            pending.append(_FileTask(file_entry=file_entry, rel_path=rel_path, parent_id=""))
        if skipped:
            logger.info("Skipping %d files already in checkpoint", skipped)
        return pending

    def _attach_parent_ids(
        self,
        pending: list[_FileTask],
        root_folder_id: str,
    ) -> list[_FileTask]:
        return [
            _FileTask(
                file_entry=task.file_entry,
                rel_path=task.rel_path,
                parent_id=self._parent_id_for(task.rel_path, root_folder_id),
            )
            for task in pending
        ]

    def _parent_id_for(self, rel_path: str, root_folder_id: str) -> str:
        parts = rel_path.split("/")
        if len(parts) == 1:
            return root_folder_id
        return self._folder_cache["/".join(parts[:-1])]

    def _prebuild_folder_map(
        self,
        rel_paths: list[str],
        root_folder_id: str,
        checkpoint: Checkpoint,
    ) -> None:
        folder_paths = collect_folder_paths(rel_paths)
        if not folder_paths:
            return

        self._folder_cache = dict(checkpoint.folder_map)
        cached_count = sum(1 for folder_path in folder_paths if folder_path in self._folder_cache)
        needed_count = len(folder_paths) - cached_count

        if cached_count:
            logger.info(
                "Using cached folder map (%d/%d folders already known)",
                cached_count,
                len(folder_paths),
            )
        if needed_count == 0:
            logger.info("All required folders already cached; skipping Drive folder setup")
            return

        logger.info("Creating %d new Google Drive folders", needed_count)
        created = 0
        for folder_path in folder_paths:
            if folder_path in self._folder_cache:
                continue

            parent_id = root_folder_id
            if "/" in folder_path:
                parent_key = folder_path.rsplit("/", 1)[0]
                parent_id = self._folder_cache[parent_key]
            folder_name = folder_path.rsplit("/", 1)[-1]
            folder_id = self.gdrive.ensure_folder(folder_name, parent_id)
            self._folder_cache[folder_path] = folder_id
            checkpoint.folder_map[folder_path] = folder_id
            created += 1
            checkpoint.updated_at = datetime.now(UTC).isoformat()
            if created % 50 == 0 or created == needed_count:
                logger.info("Folder setup progress: %d/%d new folders", created, needed_count)
                self.checkpoint_store.save(checkpoint, parts=frozenset({"folders"}))

        if created % 50 != 0:
            self.checkpoint_store.save(checkpoint, parts=frozenset({"folders"}))

    def _run_sequential(
        self,
        pending: list[_FileTask],
        checkpoint: Checkpoint,
        progress: MigrationProgressTracker,
    ) -> None:
        worker_id = 1
        for task in pending:
            self._migrate_file(task, checkpoint, self.dropbox, self.gdrive, progress, worker_id)

    def _run_parallel(
        self,
        pending: list[_FileTask],
        checkpoint: Checkpoint,
        progress: MigrationProgressTracker,
    ) -> None:
        def _worker(task: _FileTask) -> None:
            worker_id = progress.acquire_worker()
            try:
                dropbox = DropboxClient(self.secrets.dropbox)
                gdrive = GoogleDriveClient(self.secrets.google)
                self._migrate_file(task, checkpoint, dropbox, gdrive, progress, worker_id)
            finally:
                progress.release_worker(worker_id)

        with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = [executor.submit(_worker, task) for task in pending]
            for future in as_completed(futures):
                future.result()

    def _ensure_root_folder(self) -> str:
        if self.config.gdrive_root_folder_id != "root":
            return self.config.gdrive_root_folder_id
        return self.gdrive.ensure_folder(self.config.gdrive_root_folder_name, "root")

    def _migrate_file(
        self,
        task: _FileTask,
        checkpoint: Checkpoint,
        dropbox: DropboxClient,
        gdrive: GoogleDriveClient,
        progress: MigrationProgressTracker,
        worker_id: int,
    ) -> None:
        failed = False
        try:
            progress.set_phase(worker_id, task.rel_path, "starting", task.file_entry.size)

            if self.config.dry_run:
                progress.set_phase(worker_id, task.rel_path, "dry-run", task.file_entry.size)
                self._update_checkpoint(checkpoint, checkpoint.mark_skipped, task.rel_path)
                return

            progress.set_phase(worker_id, task.rel_path, "checking", task.file_entry.size)
            existing_id = gdrive.find_file(task.file_entry.name, task.parent_id)
            if existing_id:
                progress.set_phase(worker_id, task.rel_path, "skipping", task.file_entry.size)
                self._update_checkpoint(checkpoint, checkpoint.mark_skipped, task.rel_path)
                return

            progress.set_phase(worker_id, task.rel_path, "downloading", task.file_entry.size)
            mime_type, _ = mimetypes.guess_type(task.file_entry.name)
            mime_type = mime_type or "application/octet-stream"
            chunk_size = self.config.chunk_size_mb * 1024 * 1024
            stream = dropbox.download(task.file_entry.path, chunk_size=chunk_size)

            progress.set_phase(worker_id, task.rel_path, "uploading", task.file_entry.size)
            gdrive.upload_stream(
                name=task.file_entry.name,
                parent_id=task.parent_id,
                size=task.file_entry.size,
                stream=stream,
                mime_type=mime_type,
            )
            self._update_checkpoint(
                checkpoint,
                checkpoint.mark_completed,
                task.rel_path,
                task.file_entry.size,
            )
        except Exception as exc:  # noqa: BLE001 - record per-file failures and continue
            failed = True
            logger.exception("Failed to migrate %s", task.rel_path)
            self._update_checkpoint(checkpoint, checkpoint.mark_failed, task.rel_path, str(exc))
        finally:
            progress.mark_finished(worker_id, task.rel_path, failed=failed)

    def _update_checkpoint(
        self,
        checkpoint: Checkpoint,
        mark_fn: Callable[..., None],
        *args: object,
    ) -> None:
        with self._checkpoint_lock:
            mark_fn(*args)
            self.checkpoint_store.save(checkpoint, parts=frozenset({"state"}))
