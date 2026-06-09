"""Migration progress logging for sequential and parallel runs."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


@dataclass
class _WorkerState:
    worker_id: int
    rel_path: str
    phase: str
    size: int


class MigrationProgressTracker:
    """Thread-safe tracker that logs overall and per-worker migration progress."""

    def __init__(
        self,
        *,
        workers: int,
        pending_total: int,
        completed_before: int,
        total_discovered: int,
    ) -> None:
        self.workers = workers
        self.pending_total = pending_total
        self.completed_before = completed_before
        self.total_discovered = total_discovered
        self.finished_this_run = 0
        self.failed_this_run = 0
        self._active: dict[int, _WorkerState] = {}
        self._lock = threading.Lock()
        self._slot_condition = threading.Condition(self._lock)
        self._available_slots = list(range(1, workers + 1))

    def log_start(self) -> None:
        logger.info(
            "Migration started: %d pending, %d/%d already done, %d worker(s)",
            self.pending_total,
            self.completed_before,
            self.total_discovered,
            self.workers,
        )

    def acquire_worker(self) -> int:
        with self._slot_condition:
            while not self._available_slots:
                self._slot_condition.wait()
            return self._available_slots.pop(0)

    def release_worker(self, worker_id: int) -> None:
        with self._slot_condition:
            self._active.pop(worker_id, None)
            self._available_slots.append(worker_id)
            self._available_slots.sort()
            self._slot_condition.notify()

    def set_phase(self, worker_id: int, rel_path: str, phase: str, size: int = 0) -> None:
        with self._lock:
            self._active[worker_id] = _WorkerState(worker_id, rel_path, phase, size)
            self._log_snapshot()

    def mark_finished(self, worker_id: int, rel_path: str, *, failed: bool = False) -> None:
        with self._lock:
            if failed:
                self.failed_this_run += 1
            else:
                self.finished_this_run += 1
            self._active.pop(worker_id, None)
            status = "failed" if failed else "done"
            self._log_snapshot(extra=f"W{worker_id} {status} {rel_path}")

    def _log_snapshot(self, extra: str | None = None) -> None:
        done = self.completed_before + self.finished_this_run
        active_count = len(self._active)
        parts = [
            f"Progress {done}/{self.total_discovered}",
            f"{active_count}/{self.workers} workers active",
        ]
        for worker_id in sorted(self._active):
            state = self._active[worker_id]
            size_label = f" ({_format_bytes(state.size)})" if state.size else ""
            parts.append(f"W{worker_id}: {state.phase} {state.rel_path}{size_label}")
        if extra:
            parts.append(extra)
        logger.info(" | ".join(parts))

    def log_summary(self) -> None:
        logger.info(
            "Run complete: finished=%d failed=%d pending_was=%d total=%d",
            self.finished_this_run,
            self.failed_this_run,
            self.pending_total,
            self.total_discovered,
        )
