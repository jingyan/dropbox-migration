import logging

from dropbox_to_gdrive.progress import MigrationProgressTracker, _format_bytes


def test_format_bytes():
    assert _format_bytes(512) == "512 B"
    assert _format_bytes(2048) == "2.0 KB"
    assert _format_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_progress_tracker_logs_worker_phases(caplog):
    caplog.set_level(logging.INFO)
    tracker = MigrationProgressTracker(
        workers=2,
        pending_total=10,
        completed_before=90,
        total_discovered=100,
    )
    tracker.log_start()
    worker_id = tracker.acquire_worker()
    tracker.set_phase(worker_id, "Photos/a.jpg", "downloading", 1024)
    tracker.mark_finished(worker_id, "Photos/a.jpg")
    tracker.release_worker(worker_id)

    messages = [record.message for record in caplog.records]
    assert any("Migration started: 10 pending" in message for message in messages)
    assert any("W1: downloading Photos/a.jpg" in message for message in messages)
    assert any("W1 done Photos/a.jpg" in message for message in messages)
