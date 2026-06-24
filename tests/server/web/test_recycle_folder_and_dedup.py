"""Tests for:
- Blob-leak fix: identical re-upload (same md5) must not leave orphaned blobs.
- Full recursive folder delete/restore/purge with blob reclamation.
- Grouping safety: independently-deleted children are not resurrected by a folder restore.
"""

from pathlib import Path

import pytest

from supernote.client.device import DeviceClient
from supernote.client.web import WebClient
from supernote.server.constants import USER_DATA_BUCKET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_blobs(storage_root: Path) -> int:
    """Count committed blob files under the user-data bucket directory."""
    bucket_dir = storage_root / USER_DATA_BUCKET
    if not bucket_dir.exists():
        return 0
    return sum(1 for p in bucket_dir.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# 1. Identical re-upload must not leak blobs
# ---------------------------------------------------------------------------


async def test_identical_reupload_no_blob_leak(
    device_client: DeviceClient,
    web_client: WebClient,
    storage_root: Path,
) -> None:
    """Re-uploading the exact same content must not create a second blob file.

    The same-hash short-circuit in create_file returns the existing row without
    using the freshly-staged blob. The finish_upload path must delete that blob.
    """
    content = b"stable content - never changes" * 10
    path = "/dedup_no_leak.note"

    await device_client.upload_content(path, content, equipment_no="TEST")
    blobs_after_first = _count_blobs(storage_root)
    assert blobs_after_first >= 1, "At least one blob must exist after first upload"

    # Second upload of identical content — dedup short-circuit fires.
    await device_client.upload_content(path, content, equipment_no="TEST")
    blobs_after_second = _count_blobs(storage_root)

    assert blobs_after_second == blobs_after_first, (
        f"Identical re-upload must not create extra blobs: "
        f"before={blobs_after_first}, after={blobs_after_second}"
    )

    # Recycle bin must stay empty (no-op re-sync should not create a recycle entry).
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 0, "Identical re-upload must not add a recycle bin entry"


# ---------------------------------------------------------------------------
# 2. Folder delete: subtree is soft-deleted and recycle entry carries total size
# ---------------------------------------------------------------------------


async def test_folder_delete_hides_children_from_active_listing(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """Deleting a folder must make all its children invisible in the active listing."""
    # Create folder with two files.
    folder_vo = await web_client.create_folder(parent_id=0, name="ParentFolder")
    folder_id = int(folder_vo.id)

    await web_client.upload_file(parent_id=folder_id, name="child1.note", content=b"aaa" * 100)
    await web_client.upload_file(parent_id=folder_id, name="child2.note", content=b"bbb" * 100)

    # Verify children are visible.
    children_before = await web_client.list_query(directory_id=folder_id)
    assert len(children_before.user_file_vo_list) == 2

    # Delete the parent folder.
    await web_client.file_delete(id_list=[folder_id])

    # Folder must not appear at root.
    root_after = await web_client.list_query(directory_id=0)
    assert not any(e.file_name == "ParentFolder" for e in root_after.user_file_vo_list)

    # Exactly one recycle entry for the folder root.
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 1
    entry = recycle.recycle_file_vo_list[0]
    assert entry.file_name == "ParentFolder"
    assert entry.is_folder == "Y"


async def test_folder_delete_recycle_size_is_subtree_total(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """The recycle bin size for a deleted folder must equal the sum of all descendant file sizes."""
    folder_vo = await web_client.create_folder(parent_id=0, name="SizedFolder")
    folder_id = int(folder_vo.id)

    child_size = 512
    await web_client.upload_file(parent_id=folder_id, name="f1.note", content=b"x" * child_size)
    await web_client.upload_file(parent_id=folder_id, name="f2.note", content=b"y" * child_size)
    expected_size = child_size * 2

    await web_client.file_delete(id_list=[folder_id])

    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 1
    entry = recycle.recycle_file_vo_list[0]
    assert int(entry.size) == expected_size, (
        f"Recycle entry size must be the subtree total ({expected_size}), got {entry.size}"
    )


# ---------------------------------------------------------------------------
# 3. Folder restore: entire subtree comes back
# ---------------------------------------------------------------------------


async def test_folder_restore_reactivates_subtree(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """Restoring a deleted folder must reactivate the folder and all its children."""
    folder_vo = await web_client.create_folder(parent_id=0, name="RestoreMe")
    folder_id = int(folder_vo.id)

    await web_client.upload_file(parent_id=folder_id, name="inner.note", content=b"restore content")

    # Delete → restore
    await web_client.file_delete(id_list=[folder_id])

    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 1
    recycle_entry_id = int(recycle.recycle_file_vo_list[0].file_id)
    await web_client.recycle_revert(id_list=[recycle_entry_id])

    # Folder must be back at root.
    root_after = await web_client.list_query(directory_id=0)
    restored_folder = next(
        (e for e in root_after.user_file_vo_list if e.file_name == "RestoreMe"), None
    )
    assert restored_folder is not None, "Folder must be visible at root after restore"

    # Child must be visible inside the restored folder.
    children_after = await web_client.list_query(directory_id=int(restored_folder.id))
    child_names = [e.file_name for e in children_after.user_file_vo_list]
    assert "inner.note" in child_names, f"Child must be restored. Got: {child_names}"

    # Recycle bin must be empty.
    recycle_after = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_after.total == 0


# ---------------------------------------------------------------------------
# 4. Folder purge: all descendant blobs freed
# ---------------------------------------------------------------------------


async def test_folder_purge_frees_descendant_blobs(
    device_client: DeviceClient,
    web_client: WebClient,
    storage_root: Path,
) -> None:
    """Permanently deleting a folder from the recycle bin must free all descendant blobs."""
    folder_vo = await web_client.create_folder(parent_id=0, name="PurgeFolder")
    folder_id = int(folder_vo.id)

    await web_client.upload_file(
        parent_id=folder_id, name="purgeable1.note", content=b"purge me" * 50
    )
    await web_client.upload_file(
        parent_id=folder_id, name="purgeable2.note", content=b"purge me too" * 50
    )

    blobs_before_delete = _count_blobs(storage_root)

    # Soft-delete the folder — blobs stay on disk.
    await web_client.file_delete(id_list=[folder_id])
    assert _count_blobs(storage_root) == blobs_before_delete, (
        "Soft-delete must not remove blobs from disk"
    )

    # Permanently purge from recycle bin.
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 1
    recycle_entry_id = int(recycle.recycle_file_vo_list[0].file_id)
    await web_client.recycle_delete(id_list=[recycle_entry_id])

    blobs_after_purge = _count_blobs(storage_root)
    assert blobs_after_purge < blobs_before_delete, (
        "Purging a folder from recycle bin must free its descendant blobs. "
        f"before={blobs_before_delete}, after={blobs_after_purge}"
    )

    # Recycle bin must be empty.
    recycle_after = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_after.total == 0


# ---------------------------------------------------------------------------
# 5. Grouping safety: independently-deleted child not resurrected by folder restore
# ---------------------------------------------------------------------------


async def test_folder_restore_does_not_resurrect_independently_deleted_child(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """A child independently deleted before the parent folder is deleted must
    NOT be resurrected when the parent folder is later restored.

    Because the child's deleted_root_id equals its own id (stamped during its
    independent delete), not the folder's id, it is not part of the folder's
    subtree group and therefore stays in the recycle bin after the folder restore.
    """
    # Create folder with two children.
    folder_vo = await web_client.create_folder(parent_id=0, name="GroupSafetyFolder")
    folder_id = int(folder_vo.id)

    await web_client.upload_file(
        parent_id=folder_id, name="kept.note", content=b"I stay in recycle"
    )
    await web_client.upload_file(
        parent_id=folder_id, name="restored.note", content=b"I come back with the folder"
    )

    # Independently delete "kept.note" first.
    # Must supply the correct parent_id (folder_id) so the route's ownership check passes.
    listing = await web_client.list_query(directory_id=folder_id)
    kept_id = int(
        next(e for e in listing.user_file_vo_list if e.file_name == "kept.note").id
    )
    await web_client.file_delete(id_list=[kept_id], parent_id=folder_id)

    # Now delete the parent folder (only "restored.note" is still active inside it).
    await web_client.file_delete(id_list=[folder_id])

    # Recycle bin now has: "kept.note" (independent) + "GroupSafetyFolder" (folder).
    recycle_before_restore = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_before_restore.total == 2

    # Restore the folder.
    folder_recycle_entry = next(
        e for e in recycle_before_restore.recycle_file_vo_list
        if e.file_name == "GroupSafetyFolder"
    )
    await web_client.recycle_revert(id_list=[int(folder_recycle_entry.file_id)])

    # Folder and "restored.note" must be active.
    root_after = await web_client.list_query(directory_id=0)
    restored_folder = next(
        (e for e in root_after.user_file_vo_list if e.file_name == "GroupSafetyFolder"), None
    )
    assert restored_folder is not None, "Folder must be reactivated after restore"

    children_after = await web_client.list_query(directory_id=int(restored_folder.id))
    active_child_names = [e.file_name for e in children_after.user_file_vo_list]
    assert "restored.note" in active_child_names, "Child deleted with the folder must be restored"
    assert "kept.note" not in active_child_names, (
        "Independently-deleted child must NOT be resurrected by folder restore"
    )

    # "kept.note" must still be in the recycle bin.
    recycle_after = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_after.total == 1
    assert recycle_after.recycle_file_vo_list[0].file_name == "kept.note", (
        "Independently-deleted 'kept.note' must remain in recycle bin after folder restore"
    )


# ---------------------------------------------------------------------------
# 6. Restore-to-root: file whose parent was separately deleted lands at root
# ---------------------------------------------------------------------------


async def test_restore_file_with_deleted_parent_lands_at_root(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """A file independently deleted before its parent folder must be reparented to
    root when restored, not silently orphaned under the inactive parent.

    Scenario:
    1. Create Projects/meeting.note.
    2. Delete meeting.note (independent delete → own recycle entry).
    3. Delete Projects folder.
    4. Restore meeting.note only.
    5. meeting.note must be visible at root because Projects is still deleted.
    """
    # 1. Create folder and upload file inside it.
    folder_vo = await web_client.create_folder(parent_id=0, name="OrphanProjects")
    folder_id = int(folder_vo.id)

    await web_client.upload_file(
        parent_id=folder_id, name="meeting.note", content=b"orphan test content"
    )

    # 2. Delete meeting.note independently.
    listing = await web_client.list_query(directory_id=folder_id)
    file_id = int(
        next(e for e in listing.user_file_vo_list if e.file_name == "meeting.note").id
    )
    await web_client.file_delete(id_list=[file_id], parent_id=folder_id)

    # 3. Delete the parent folder.
    await web_client.file_delete(id_list=[folder_id])

    # Recycle bin now has: "meeting.note" + "OrphanProjects".
    recycle_before = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_before.total == 2

    # 4. Restore meeting.note only.
    file_recycle_entry = next(
        e for e in recycle_before.recycle_file_vo_list if e.file_name == "meeting.note"
    )
    await web_client.recycle_revert(id_list=[int(file_recycle_entry.file_id)])

    # 5. meeting.note must surface at root, not be orphaned under the deleted folder.
    root_after = await web_client.list_query(directory_id=0)
    root_names = [e.file_name for e in root_after.user_file_vo_list]
    assert "meeting.note" in root_names, (
        f"Restored file must be visible at root when its parent is deleted. "
        f"Root contents: {root_names}"
    )

    # The folder's recycle entry must still be present (we only restored the file).
    recycle_after = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_after.total == 1
    assert recycle_after.recycle_file_vo_list[0].file_name == "OrphanProjects", (
        "Folder recycle entry must remain after restoring only the file"
    )
