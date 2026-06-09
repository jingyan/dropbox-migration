from unittest.mock import MagicMock

from dropbox_to_gdrive.checkpoint import Checkpoint
from dropbox_to_gdrive.config import Config
from dropbox_to_gdrive.dropbox_client import DropboxFile
from dropbox_to_gdrive.migrator import Migrator, collect_folder_paths


def _file(path: str, name: str, size: int = 100) -> DropboxFile:
    return DropboxFile(
        path=path,
        name=name,
        size=size,
        content_hash=None,
        server_modified=None,
    )


def test_collect_folder_paths_sorted_by_depth():
    paths = [
        "Photos/2024/vacation/img.jpg",
        "Photos/2024/img.jpg",
        "Docs/readme.txt",
    ]
    assert collect_folder_paths(paths) == [
        "Docs",
        "Photos",
        "Photos/2024",
        "Photos/2024/vacation",
    ]


def test_collect_folder_paths_empty_for_root_files():
    assert collect_folder_paths(["readme.txt"]) == []


def test_discover_files_uses_cached_manifest():
    cached = _file("/Photos/a.jpg", "a.jpg")
    checkpoint = Checkpoint(
        dropbox_root_path="/Photos",
        file_manifest={"a.jpg": cached.to_dict()},
    )
    dropbox = MagicMock()
    migrator = Migrator(
        config=Config(dropbox_access_token="token", dropbox_root_path="/Photos"),
        secrets=MagicMock(),
        checkpoint_store=MagicMock(),
        dropbox_client=dropbox,
        gdrive_client=MagicMock(),
    )

    files = migrator._discover_files(checkpoint)

    assert len(files) == 1
    assert files[0].name == "a.jpg"
    dropbox.iter_files.assert_not_called()


def test_discover_files_rescans_when_manifest_missing():
    checkpoint = Checkpoint()
    dropbox = MagicMock()
    dropbox.iter_files.return_value = [_file("/Photos/a.jpg", "a.jpg")]
    store = MagicMock()

    migrator = Migrator(
        config=Config(dropbox_access_token="token", dropbox_root_path="/Photos"),
        secrets=MagicMock(),
        checkpoint_store=store,
        dropbox_client=dropbox,
        gdrive_client=MagicMock(),
    )

    files = migrator._discover_files(checkpoint)

    assert len(files) == 1
    assert checkpoint.file_manifest["a.jpg"]["name"] == "a.jpg"
    store.save.assert_called_once()


def test_discover_files_rescans_when_force_relist_enabled():
    cached = _file("/Photos/a.jpg", "a.jpg")
    checkpoint = Checkpoint(
        dropbox_root_path="/Photos",
        file_manifest={"a.jpg": cached.to_dict()},
    )
    dropbox = MagicMock()
    dropbox.iter_files.return_value = [_file("/Photos/a.jpg", "a.jpg")]
    store = MagicMock()

    migrator = Migrator(
        config=Config(
            dropbox_access_token="token",
            dropbox_root_path="/Photos",
            force_relist=True,
        ),
        secrets=MagicMock(),
        checkpoint_store=store,
        dropbox_client=dropbox,
        gdrive_client=MagicMock(),
    )

    migrator._discover_files(checkpoint)

    dropbox.iter_files.assert_called_once_with("/Photos")
