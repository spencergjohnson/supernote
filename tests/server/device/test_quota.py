"""Tests for quota enforcement: pre-flight check, authoritative check, capacity reporting."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from supernote.client.device import DeviceClient
from supernote.client.exceptions import ApiException
from supernote.client.web import WebClient
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager

TEST_USERNAME = "test@example.com"


async def _set_quota(session_manager: DatabaseSessionManager, email: str, quota_bytes: int) -> None:
    """Helper: set a user's total_capacity in the database."""
    async with session_manager.session() as session:
        result = await session.execute(select(UserDO).where(UserDO.email == email))
        user = result.scalar_one()
        user.total_capacity = str(quota_bytes)
        await session.commit()


async def test_capacity_query_echoes_real_quota_device(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Device capacity endpoint must return the user's actual quota, not a hardcoded value."""
    # Default quota is 10 GB
    cap = await device_client.get_capacity()
    assert cap.allocation_vo is not None
    assert cap.allocation_vo.allocated == 10 * 1024 * 1024 * 1024

    # Set a custom quota
    custom_quota = 2 * 1024 * 1024 * 1024  # 2 GB
    await _set_quota(session_manager, TEST_USERNAME, custom_quota)

    cap_after = await device_client.get_capacity()
    assert cap_after.allocation_vo is not None
    assert cap_after.allocation_vo.allocated == custom_quota


async def test_capacity_query_echoes_real_quota_web(
    web_client: WebClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Web capacity endpoint must return the user's actual quota, not a hardcoded value."""
    cap = await web_client.get_capacity_web()
    assert cap.total_capacity == 10 * 1024 * 1024 * 1024

    custom_quota = 500 * 1024 * 1024  # 500 MB
    await _set_quota(session_manager, TEST_USERNAME, custom_quota)

    cap_after = await web_client.get_capacity_web()
    assert cap_after.total_capacity == custom_quota


async def test_upload_exceeds_quota_rejected(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """An upload whose size exceeds the user's quota must be rejected with QUOTA_EXCEEDED."""
    # Set a very small quota (1 byte)
    await _set_quota(session_manager, TEST_USERNAME, 1)

    content = b"hello world"  # 11 bytes > 1 byte quota
    with pytest.raises(ApiException) as excinfo:
        await device_client.upload_content("/quota_test.txt", content, equipment_no="TEST")

    assert "E0728" in str(excinfo.value) or "quota" in str(excinfo.value).lower()


async def test_in_quota_upload_succeeds(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """An upload that fits within quota must succeed."""
    # Set a comfortable quota
    await _set_quota(session_manager, TEST_USERNAME, 1024 * 1024)  # 1 MB

    content = b"x" * 512  # 512 bytes — well within quota
    result = await device_client.upload_content("/in_quota.txt", content, equipment_no="TEST")
    assert result.id is not None


async def test_quota_reject_does_not_create_file_row(
    device_client: DeviceClient,
    web_client: WebClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """A quota-rejected upload must leave no VFS file row (sync safety regression)."""
    await _set_quota(session_manager, TEST_USERNAME, 1)

    with pytest.raises(ApiException):
        await device_client.upload_content("/rejected.txt", b"too big", equipment_no="TEST")

    # No file should be listed
    result = await device_client.list_folder("/", "TEST")
    names = [e.name for e in result.entries]
    assert "rejected.txt" not in names


async def test_capacity_used_tracks_upload(
    device_client: DeviceClient,
) -> None:
    """Used capacity must increase by the exact blob size after a successful upload."""
    cap_before = await device_client.get_capacity()

    content = b"z" * 4096  # 4 KB
    await device_client.upload_content("/track_test.txt", content, equipment_no="TEST")

    cap_after = await device_client.get_capacity()
    assert cap_after.used == cap_before.used + 4096


async def test_same_size_overwrite_at_full_quota_succeeds(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Overwriting a file with same-size content while exactly at quota must succeed.

    Regression: the quota check must be replace-aware. The old version's bytes are
    freed by the overwrite, so the net delta is zero and the upload must not be
    falsely rejected.
    """
    content_v1 = b"a" * 1000
    await device_client.upload_content("/doc.txt", content_v1, equipment_no="TEST")

    # Pin quota to exactly the current usage — no headroom for additive growth.
    used = (await device_client.get_capacity()).used
    await _set_quota(session_manager, TEST_USERNAME, used)

    # Overwrite with different content of the same size: net delta is 0.
    content_v2 = b"b" * 1000
    result = await device_client.upload_content(
        "/doc.txt", content_v2, equipment_no="TEST"
    )
    assert result.id is not None


async def test_identical_resync_at_full_quota_succeeds(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Re-syncing byte-identical content while at quota is a no-op and must succeed."""
    content = b"c" * 2048
    await device_client.upload_content("/resync.txt", content, equipment_no="TEST")

    used = (await device_client.get_capacity()).used
    await _set_quota(session_manager, TEST_USERNAME, used)

    # Identical re-sync (same md5) — must short-circuit, never rejected.
    result = await device_client.upload_content(
        "/resync.txt", content, equipment_no="TEST"
    )
    assert result.id is not None


async def test_overwrite_with_larger_content_over_quota_rejected(
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """An overwrite that genuinely grows usage past quota must still be rejected."""
    content_v1 = b"a" * 1000
    await device_client.upload_content("/grow.txt", content_v1, equipment_no="TEST")

    # Allow at most the original size + a little; the larger overwrite won't fit.
    await _set_quota(session_manager, TEST_USERNAME, 1500)

    content_v2 = b"b" * 4000  # net delta = 4000 - 1000 = 3000 > 1500 headroom
    with pytest.raises(ApiException) as excinfo:
        await device_client.upload_content("/grow.txt", content_v2, equipment_no="TEST")
    assert "E0728" in str(excinfo.value) or "quota" in str(excinfo.value).lower()

    # The original file must remain intact (overwrite was rejected atomically).
    result = await device_client.list_folder("/", "TEST")
    names = [e.name for e in result.entries]
    assert "grow.txt" in names
