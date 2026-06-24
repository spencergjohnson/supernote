"""Tests for overwrite de-duplication: re-uploading a file to the same path
should create exactly one active VFS row, and the prior version should appear
in the recycle bin (unless the content is identical).
"""

import hashlib

from supernote.client.device import DeviceClient
from supernote.client.web import WebClient


async def test_overwrite_leaves_one_active_row(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """Re-uploading a file must leave exactly one active row — not two."""
    path = "/overwrite_test.note"
    content_v1 = b"version one content"
    content_v2 = b"version two content - edited"

    # Upload v1
    await device_client.upload_content(path, content_v1, equipment_no="TEST")

    # Verify one active file at root
    listing_v1 = await device_client.list_folder("/", "TEST")
    root_notes_before = [e for e in listing_v1.entries if e.name == "overwrite_test.note"]
    assert len(root_notes_before) == 1

    # Upload v2 to the same path
    await device_client.upload_content(path, content_v2, equipment_no="TEST")

    # Should still be exactly one active file at root
    listing_v2 = await device_client.list_folder("/", "TEST")
    root_notes_after = [e for e in listing_v2.entries if e.name == "overwrite_test.note"]
    assert len(root_notes_after) == 1, (
        f"Expected 1 active entry after overwrite, got {len(root_notes_after)}"
    )


async def test_overwrite_sends_prior_version_to_recycle(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """The prior version of an overwritten file must appear in the recycle bin."""
    path = "/recycle_overwrite.note"
    content_v1 = b"first version"
    content_v2 = b"second version"

    await device_client.upload_content(path, content_v1, equipment_no="TEST")
    await device_client.upload_content(path, content_v2, equipment_no="TEST")

    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    recycled_names = [e.file_name for e in recycle.recycle_file_vo_list]
    assert "recycle_overwrite.note" in recycled_names


async def test_overwrite_quota_reflects_only_new_version(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """After overwriting, used quota must only count the new version's size."""
    path = "/quota_overwrite.note"
    content_v1 = b"a" * 1000  # 1000 bytes
    content_v2 = b"b" * 500   # 500 bytes

    await device_client.upload_content(path, content_v1, equipment_no="TEST")
    cap_v1 = await device_client.get_capacity()

    await device_client.upload_content(path, content_v2, equipment_no="TEST")
    cap_v2 = await device_client.get_capacity()

    # Used should decrease (v1 was larger than v2)
    assert cap_v2.used < cap_v1.used


async def test_same_md5_overwrite_is_noop(
    device_client: DeviceClient,
    web_client: WebClient,
) -> None:
    """Re-syncing identical content must not add a recycle bin entry (no-op)."""
    path = "/noop_resync.note"
    content = b"identical content - no change"

    await device_client.upload_content(path, content, equipment_no="TEST")

    # Re-upload the exact same content
    await device_client.upload_content(path, content, equipment_no="TEST")

    # The recycle bin must still be empty (same md5 → no-op)
    recycle = await web_client.recycle_list(page_no=1, page_size=50)
    assert recycle.total == 0, (
        "Identical re-upload should not add a recycle bin entry"
    )


async def test_overwrite_get_file_info_resolves(
    device_client: DeviceClient,
) -> None:
    """After overwriting, querying by path must resolve without MultipleResultsFound."""
    path = "/resolve_overwrite.note"

    await device_client.upload_content(path, b"v1 content", equipment_no="TEST")
    await device_client.upload_content(path, b"v2 content", equipment_no="TEST")
    await device_client.upload_content(path, b"v3 content", equipment_no="TEST")

    # query_by_path uses resolve_path (scalar_one_or_none) — must not raise
    result = await device_client.query_by_path(path, "TEST")
    assert result.entries_vo is not None

    # Content must be v3
    content_hash = hashlib.md5(b"v3 content").hexdigest()
    assert result.entries_vo.content_hash == content_hash
