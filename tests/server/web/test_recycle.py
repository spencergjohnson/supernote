from pathlib import Path

import pytest

from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient
from supernote.server.constants import IMMUTABLE_SYSTEM_DIRECTORIES


async def test_soft_delete_to_recycle(
    web_client: WebClient,
) -> None:
    # Create a folder
    await web_client.create_folder(parent_id=0, name="TestFolder")

    # Get ID of folder
    # Use Web Listing to find ID
    list_result = await web_client.list_query(directory_id=0)
    entry = next(
        e for e in list_result.user_file_vo_list if e.file_name == "TestFolder"
    )
    item_id = int(entry.id)

    # Delete (soft delete to recycle bin)
    await web_client.file_delete(id_list=[item_id])

    # Verify not in main folder
    list_folder_result = await web_client.list_query(directory_id=0)
    assert not any(
        e.file_name == "TestFolder" for e in list_folder_result.user_file_vo_list
    )

    # Verify in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 1
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    assert recycle_list_result.recycle_file_vo_list[0].file_name == "TestFolder"
    assert recycle_list_result.recycle_file_vo_list[0].is_folder == "Y"


async def test_recycle_revert(
    web_client: WebClient,
) -> None:
    # Create and delete a folder
    await web_client.create_folder(parent_id=0, name="ToRestore")

    list_result = await web_client.list_query(directory_id=0)
    entry = next(e for e in list_result.user_file_vo_list if e.file_name == "ToRestore")
    item_id = int(entry.id)

    await web_client.file_delete(id_list=[item_id])

    # Get recycle bin item ID
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    recycle_id = int(recycle_list_result.recycle_file_vo_list[0].file_id)

    # Revert from recycle bin
    await web_client.recycle_revert(id_list=[recycle_id])

    # Verify back in main folder
    list_folder_result = await web_client.list_query(directory_id=0)
    assert any(e.file_name == "ToRestore" for e in list_folder_result.user_file_vo_list)

    # Verify not in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result.total == 0


async def test_recycle_permanent_delete(
    web_client: WebClient,
) -> None:
    # Create and delete a folder
    await web_client.create_folder(parent_id=0, name="ToDelete")

    list_result = await web_client.list_query(directory_id=0)
    entry = next(e for e in list_result.user_file_vo_list if e.file_name == "ToDelete")
    item_id = int(entry.id)

    await web_client.file_delete(id_list=[item_id])

    # Get recycle bin item ID
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.recycle_file_vo_list
    assert len(recycle_list_result.recycle_file_vo_list) == 1
    recycle_id = int(recycle_list_result.recycle_file_vo_list[0].file_id)

    # Permanently delete from recycle bin
    await web_client.recycle_delete(id_list=[recycle_id])

    # Verify not in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 0


async def test_recycle_clear(
    web_client: WebClient,
) -> None:
    # Default folders
    list_folder_result = await web_client.list_query(directory_id=0)
    assert list_folder_result
    assert len(list_folder_result.user_file_vo_list) == 6

    # Create and delete multiple folders
    for name in ["Folder1", "Folder2", "Folder3"]:
        await web_client.create_folder(parent_id=0, name=name)

    list_result = await web_client.list_query(directory_id=0)
    assert list_result.total == 9

    # Delete ONLY the new folders (skip immutable system folders)
    ids_to_delete = [
        int(f.id)
        for f in list_result.user_file_vo_list
        if f.file_name not in IMMUTABLE_SYSTEM_DIRECTORIES
    ]
    assert len(ids_to_delete) == 3
    await web_client.file_delete(id_list=ids_to_delete)

    # Verify 3 items in recycle bin
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 3

    # Clear recycle bin
    await web_client.recycle_clear()

    # Verify recycle bin is empty
    recycle_list_result = await web_client.recycle_list(page_no=1, page_size=20)
    assert recycle_list_result
    assert recycle_list_result.total == 0


async def test_delete_wrong_parent(
    web_client: WebClient,
) -> None:
    # 1. Create Parent Folder (in Root)
    parent_vo = await web_client.create_folder(parent_id=0, name="ParentFolder")
    parent_id = int(parent_vo.id)

    # 2. Create Child Folder (in Parent)
    child_vo = await web_client.create_folder(parent_id=parent_id, name="ChildFolder")
    child_id = int(child_vo.id)

    # 3. Try to delete Child using WRONG parent (Root=0)
    with pytest.raises(ApiException) as excinfo:
        await web_client.file_delete(id_list=[child_id], parent_id=0)

    assert "File " in str(excinfo.value)
    assert "is not in directory 0" in str(excinfo.value)

    # 4. Delete Child using CORRECT parent
    await web_client.file_delete(id_list=[child_id], parent_id=parent_id)

    # 5. Verify deleted from parent
    # Note: list_query for parent
    list_result = await web_client.list_query(directory_id=parent_id)
    assert not any(f.id == str(child_id) for f in list_result.user_file_vo_list)


async def test_recycle_size_in_capacity_response(
    web_client: WebClient,
    device_client: DeviceClient,
) -> None:
    """capacity/query must expose recycle_size as a separate field that excludes active files."""
    # Upload a file, then delete it to the recycle bin
    content = b"x" * 2048
    await device_client.upload_content("/recycle_size_test.note", content, equipment_no="TEST")

    cap_before = await web_client.get_capacity_web()
    used_before = cap_before.used_capacity

    # Soft-delete to recycle bin
    result = await device_client.query_by_path("/recycle_size_test.note", "TEST")
    assert result.entries_vo is not None
    file_id = int(result.entries_vo.id)
    await web_client.file_delete(id_list=[file_id])

    cap_after = await web_client.get_capacity_web()
    # Active usage should have dropped (file is no longer active)
    assert cap_after.used_capacity == used_before - 2048
    # Recycle size should be positive now
    assert cap_after.recycle_size >= 2048


async def test_recycle_list_includes_total_size(
    web_client: WebClient,
    device_client: DeviceClient,
) -> None:
    """recycle/list/query must include totalSize aggregating the sizes of recycled items."""
    content = b"y" * 1024
    await device_client.upload_content("/total_size_test.note", content, equipment_no="TEST")

    result = await device_client.query_by_path("/total_size_test.note", "TEST")
    assert result.entries_vo is not None
    await web_client.file_delete(id_list=[int(result.entries_vo.id)])

    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total_size >= 1024


async def test_purge_recycle_frees_blob(
    web_client: WebClient,
    device_client: DeviceClient,
    storage_root: Path,
) -> None:
    """Permanently deleting a recycle bin item must delete the underlying blob from disk."""
    content = b"purgeable content" * 100
    await device_client.upload_content("/purgeable.note", content, equipment_no="TEST")

    query = await device_client.query_by_path("/purgeable.note", "TEST")
    assert query.entries_vo is not None
    file_id = int(query.entries_vo.id)

    # Count blob files after upload
    bucket_dir = storage_root / "supernote-user-data"
    blobs_after_upload = list(bucket_dir.rglob("*")) if bucket_dir.exists() else []
    blob_count_after_upload = sum(1 for p in blobs_after_upload if p.is_file())

    # Soft-delete to recycle bin
    await web_client.file_delete(id_list=[file_id])

    # Blob is still on disk after soft-delete
    blobs_after_delete = list(bucket_dir.rglob("*")) if bucket_dir.exists() else []
    assert sum(1 for p in blobs_after_delete if p.is_file()) == blob_count_after_upload

    # Permanently delete from bin — should free the blob
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    recycle_id = int(recycle.recycle_file_vo_list[0].file_id)
    await web_client.recycle_delete(id_list=[recycle_id])

    blobs_after_purge = list(bucket_dir.rglob("*")) if bucket_dir.exists() else []
    blob_count_after_purge = sum(1 for p in blobs_after_purge if p.is_file())
    assert blob_count_after_purge < blob_count_after_upload, (
        "Purging a recycle bin item must free the underlying blob file"
    )


async def test_clear_recycle_frees_blobs(
    web_client: WebClient,
    device_client: DeviceClient,
) -> None:
    """Clearing the entire recycle bin must delete all underlying blobs."""
    content = b"clear me" * 200
    await device_client.upload_content("/clear_test.note", content, equipment_no="TEST")

    query = await device_client.query_by_path("/clear_test.note", "TEST")
    assert query.entries_vo is not None
    file_id = int(query.entries_vo.id)

    await web_client.file_delete(id_list=[file_id])
    await web_client.recycle_clear()

    # Bin is empty
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 0


async def test_restore_returns_item_to_active(
    web_client: WebClient,
    device_client: DeviceClient,
) -> None:
    """Restoring a recycle bin item must make it visible in the active file listing again."""
    await device_client.upload_content("/restore_me.note", b"restore content", equipment_no="TEST")

    query = await device_client.query_by_path("/restore_me.note", "TEST")
    assert query.entries_vo is not None
    await web_client.file_delete(id_list=[int(query.entries_vo.id)])

    # Verify gone from active listing
    listing_after_delete = await device_client.list_folder("/", "TEST")
    assert not any(e.name == "restore_me.note" for e in listing_after_delete.entries)

    # Restore
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    recycle_id = int(recycle.recycle_file_vo_list[0].file_id)
    await web_client.recycle_revert(id_list=[recycle_id])

    # Verify back in active listing
    listing_after_restore = await device_client.list_folder("/", "TEST")
    assert any(e.name == "restore_me.note" for e in listing_after_restore.entries)


async def test_restore_after_overwrite_autorenames(
    web_client: WebClient,
    device_client: DeviceClient,
) -> None:
    """Restoring an older version whose path is now occupied auto-renames it.

    Scenario:
    - Upload v1 → active
    - Upload v2 (overwrite) → v1 soft-deleted to bin, v2 active
    - Restore v1 from bin → path is occupied by v2, so v1 gets a unique name
    Expected:
    - Exactly one active entry named 'clash.note' (v2)
    - Exactly one active entry named 'clash (1).note' (restored v1)
    - query_by_path('/clash.note') still resolves without MultipleResultsFound
    """
    path = "/clash.note"

    await device_client.upload_content(path, b"v1 content", equipment_no="TEST")
    await device_client.upload_content(path, b"v2 content", equipment_no="TEST")

    # v1 should be in the recycle bin
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 1
    recycle_entry_id = int(recycle.recycle_file_vo_list[0].file_id)

    # Restore v1
    await web_client.recycle_revert(id_list=[recycle_entry_id])

    # Active listing must have exactly two entries for clash.note base name
    listing = await device_client.list_folder("/", "TEST")
    active_names = [e.name for e in listing.entries]
    assert "clash.note" in active_names, "v2 must still be active at original path"
    assert "clash (1).note" in active_names, "v1 must be restored under a unique name"
    clash_entries = [n for n in active_names if n.startswith("clash")]
    assert len(clash_entries) == 2, f"Expected exactly 2 'clash*' entries, got {clash_entries}"

    # query_by_path on the original path must not raise MultipleResultsFound
    result = await device_client.query_by_path(path, "TEST")
    assert result.entries_vo is not None, "query_by_path must resolve the active v2 row"

    # Recycle bin must be empty after the restore
    recycle_after = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle_after.total == 0
