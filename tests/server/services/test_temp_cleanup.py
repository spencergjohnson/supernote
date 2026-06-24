"""Unit tests for LocalBlobStorage.cleanup_temp (mtime-guarded orphan sweeper)."""

import os
import time
from pathlib import Path

import pytest

from supernote.server.services.blob import LocalBlobStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalBlobStorage:
    return LocalBlobStorage(tmp_path)


def _create_temp_file(storage: LocalBlobStorage, name: str = "test.tmp", age_seconds: float = 0) -> Path:
    """Create a *.tmp file in <storage_root>/temp/ and optionally backdate its mtime."""
    temp_dir = storage.root / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    path = temp_dir / name
    path.write_bytes(b"orphan content")
    if age_seconds > 0:
        old_time = time.time() - age_seconds
        os.utime(path, (old_time, old_time))
    return path


async def test_stale_temp_file_is_removed(storage: LocalBlobStorage) -> None:
    """A *.tmp file older than max_age_seconds must be deleted."""
    path = _create_temp_file(storage, "stale.tmp", age_seconds=7200)  # 2 hours old
    assert path.exists()

    removed = await storage.cleanup_temp(max_age_seconds=3600)
    assert removed == 1
    assert not path.exists()


async def test_fresh_temp_file_is_kept(storage: LocalBlobStorage) -> None:
    """A *.tmp file younger than max_age_seconds must NOT be deleted."""
    path = _create_temp_file(storage, "fresh.tmp", age_seconds=0)  # just created
    assert path.exists()

    removed = await storage.cleanup_temp(max_age_seconds=3600)
    assert removed == 0
    assert path.exists()


async def test_only_tmp_files_are_considered(storage: LocalBlobStorage) -> None:
    """Non-*.tmp files in the temp directory must not be touched."""
    temp_dir = storage.root / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    not_tmp = temp_dir / "important.dat"
    not_tmp.write_bytes(b"important")
    old_time = time.time() - 7200
    os.utime(not_tmp, (old_time, old_time))

    removed = await storage.cleanup_temp(max_age_seconds=3600)
    assert removed == 0
    assert not_tmp.exists()


async def test_missing_temp_dir_returns_zero(storage: LocalBlobStorage) -> None:
    """cleanup_temp must return 0 without error when the temp directory does not exist."""
    # temp dir was never created
    removed = await storage.cleanup_temp(max_age_seconds=3600)
    assert removed == 0


async def test_mixed_ages_only_stale_removed(storage: LocalBlobStorage) -> None:
    """With a mix of stale and fresh files, only stale ones are removed."""
    stale = _create_temp_file(storage, "stale.tmp", age_seconds=7200)
    fresh = _create_temp_file(storage, "fresh.tmp", age_seconds=0)

    removed = await storage.cleanup_temp(max_age_seconds=3600)
    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()


async def test_concurrent_removal_is_tolerated(storage: LocalBlobStorage) -> None:
    """cleanup_temp must not raise if a file disappears between listing and deletion (race tolerance)."""
    path = _create_temp_file(storage, "vanishing.tmp", age_seconds=7200)
    # Remove the file to simulate a concurrent upload completing its rename
    path.unlink()

    # Must complete without exception
    removed = await storage.cleanup_temp(max_age_seconds=3600)
    assert removed == 0
