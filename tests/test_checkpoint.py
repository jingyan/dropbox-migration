from dropbox_to_gdrive.checkpoint import Checkpoint, CheckpointStore, MigrationStats


def test_checkpoint_roundtrip(tmp_path):
    uri = f"file://{tmp_path / 'checkpoint.json'}"
    store = CheckpointStore(uri)

    checkpoint = Checkpoint(
        gdrive_root_folder_id="folder123",
        completed_paths={"docs/a.txt"},
        stats=MigrationStats(files_discovered=1, files_migrated=1, bytes_migrated=10),
    )
    store.save(checkpoint)
    loaded = store.load()

    assert loaded.gdrive_root_folder_id == "folder123"
    assert loaded.completed_paths == {"docs/a.txt"}
    assert loaded.stats.files_migrated == 1
    assert loaded.stats.bytes_migrated == 10


def test_checkpoint_mark_completed():
    checkpoint = Checkpoint()
    checkpoint.mark_completed("photos/cat.jpg", 2048)

    assert "photos/cat.jpg" in checkpoint.completed_paths
    assert checkpoint.stats.files_migrated == 1
    assert checkpoint.stats.bytes_migrated == 2048
