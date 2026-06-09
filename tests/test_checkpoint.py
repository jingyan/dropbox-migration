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
