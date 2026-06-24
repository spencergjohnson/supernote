import shutil
from pathlib import Path

from aiohttp.test_utils import TestClient
from sqlalchemy import delete

from supernote.client.device import DeviceClient
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager


async def test_sync_start_syn_type(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_root: Path,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    # Clear storage root for test
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    # Clear VFS state for this user
    async with session_manager.session() as session:
        # Delete all nodes for simplicity. In a real shared DB this would be bad,
        # but here we are in a test environment with a shared in-memory DB.
        # Ideally we filter by user_id but we need to resolve it first.
        await session.execute(delete(UserFileDO))
        await session.commit()
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["synType"] is False  # Empty storage

    # 2. Add a dummy file
    await device_client.upload_content(
        "Note/test.note", b"content", equipment_no="test"
    )

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is True  # Non-empty storage


async def test_sync_start_syn_type_folders_only(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_root: Path,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """A server holding only folders (no files) must stay in init mode.

    Regression test: if ``synType`` were ``True`` while the server has no
    files, the device interprets its missing files as remote deletions and
    wipes them locally. A folders-only server must therefore report
    ``synType=False`` (initialization mode).
    """
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    async with session_manager.session() as session:
        await session.execute(delete(UserFileDO))
        await session.commit()

    # Create a folder but no files.
    await device_client.create_folder("Note", equipment_no="test")

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["synType"] is False  # Folders only -> still initialization mode


async def test_sync_lock(client: TestClient, auth_headers: dict[str, str]) -> None:
    # 1. Start sync from SN123
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 2. Try sync from SN456 (same user), should get 409
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 409
    data = await resp.json()
    assert data["errorCode"] == "E0078"

    # 3. End sync from SN123
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123", "flag": "true"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 4. Now SN456 should be able to sync
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    assert (await resp.json())["success"] is True
