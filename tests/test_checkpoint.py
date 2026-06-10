from dropbox_to_gdrive.checkpoint import Checkpoint, CheckpointStore
from dropbox_to_gdrive.dropbox_client import DropboxFile


def test_checkpoint_manifest_roundtrip(tmp_path):
    uri = f"file://{tmp_path / 'checkpoint.json'}"
    store = CheckpointStore(uri)

    file_entry = DropboxFile(
        path="/Photos/cat.jpg",
        name="cat.jpg",
        size=1024,
        content_hash="abc",
        server_modified="2024-01-01T00:00:00",
    )
    checkpoint = Checkpoint(
        dropbox_root_path="/Photos",
        file_manifest={"cat.jpg": file_entry.to_dict()},
    )
    store.save(checkpoint)
    loaded = store.load()

    assert loaded.dropbox_root_path == "/Photos"
    assert loaded.file_manifest["cat.jpg"]["name"] == "cat.jpg"
    assert DropboxFile.from_dict(loaded.file_manifest["cat.jpg"]).size == 1024


def test_checkpoint_folder_map_roundtrip(tmp_path):
    uri = f"file://{tmp_path / 'checkpoint.json'}"
    store = CheckpointStore(uri)

    checkpoint = Checkpoint(
        folder_map={
            "Photos": "folder-photos",
            "Photos/2024": "folder-2024",
        }
    )
    store.save(checkpoint)
    loaded = store.load()

    assert loaded.folder_map == checkpoint.folder_map


def test_checkpoint_split_files(tmp_path):
    uri = f"file://{tmp_path / 'checkpoint.json'}"
    store = CheckpointStore(uri)
    checkpoint = Checkpoint(
        dropbox_root_path="/Photos",
        file_manifest={"a.jpg": {"path": "/Photos/a.jpg", "name": "a.jpg", "size": 1}},
        folder_map={"Photos": "folder-id"},
        completed_paths={"done.jpg"},
    )

    store.save(checkpoint)

    state_path = tmp_path / "checkpoint.json"
    manifest_path = tmp_path / "checkpoint.manifest.json"
    folders_path = tmp_path / "checkpoint.folders.json"

    assert state_path.exists()
    assert manifest_path.exists()
    assert folders_path.exists()
    assert "file_manifest" not in state_path.read_text(encoding="utf-8")
    assert "folder_map" not in state_path.read_text(encoding="utf-8")
    assert store.load().completed_paths == {"done.jpg"}


def test_checkpoint_save_state_only(tmp_path):
    uri = f"file://{tmp_path / 'checkpoint.json'}"
    store = CheckpointStore(uri)
    checkpoint = Checkpoint(
        file_manifest={"a.jpg": {"path": "/Photos/a.jpg", "name": "a.jpg", "size": 1}},
        completed_paths={"a.jpg"},
    )
    store.save(checkpoint)
    manifest_mtime = (tmp_path / "checkpoint.manifest.json").stat().st_mtime

    checkpoint.completed_paths.add("b.jpg")
    store.save(checkpoint, parts=frozenset({"state"}))

    assert (tmp_path / "checkpoint.manifest.json").stat().st_mtime == manifest_mtime
    assert store.load().completed_paths == {"a.jpg", "b.jpg"}


def test_checkpoint_legacy_monolithic_load(tmp_path):
    uri = f"file://{tmp_path / 'checkpoint.json'}"
    legacy = {
        "version": 2,
        "dropbox_root_path": "/Photos",
        "file_manifest": {"a.jpg": {"path": "/Photos/a.jpg", "name": "a.jpg", "size": 1}},
        "folder_map": {"Photos": "folder-id"},
        "completed_paths": ["a.jpg"],
        "stats": {},
    }
    (tmp_path / "checkpoint.json").write_text(
        __import__("json").dumps(legacy),
        encoding="utf-8",
    )

    loaded = CheckpointStore(uri).load()

    assert loaded.file_manifest["a.jpg"]["name"] == "a.jpg"
    assert loaded.folder_map["Photos"] == "folder-id"
