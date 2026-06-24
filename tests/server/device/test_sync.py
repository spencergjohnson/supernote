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

    # 2. Upload a file (no sync end yet, so the init marker is still absent)
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
    assert data["synType"] is False  # Files exist but init marker not set yet

    # 3. End sync successfully -> sets the init marker
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123456", "flag": "true"},
        headers=auth_headers,
    )
    assert resp.status == 200

    # 4. Now that the marker is set and files exist, differential sync is allowed
    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["synType"] is True  # Non-empty storage + init confirmed


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


async def test_sync_start_syn_type_files_but_not_initialized(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_root: Path,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """Server with files but no init marker must stay in init mode.

    Regression test: uploading files alone must not flip synType to True.
    The init marker is only set after a successful synchronous/end, so if the
    device uploads some files and the sync is interrupted (or the DB is reset
    and files are uploaded on a fresh run), the next sync start must still
    return synType=False so the device uploads rather than deletes.
    """
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    async with session_manager.session() as session:
        await session.execute(delete(UserFileDO))
        await session.commit()

    # Upload a file without ever calling synchronous/end (no init marker).
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
    assert data["success"] is True
    assert data["synType"] is False  # Files exist but no init marker -> safe init mode


async def test_sync_end_sets_initialized_marker(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_root: Path,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """A successful synchronous/end sets the init marker, enabling differential sync.

    After the very first successful sync end the server should return synType=True
    on the next start (provided files exist), allowing normal differential sync.
    """
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    async with session_manager.session() as session:
        await session.execute(delete(UserFileDO))
        await session.commit()

    await device_client.upload_content(
        "Note/test.note", b"content", equipment_no="test"
    )

    # End the sync successfully to record the init marker.
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123456", "flag": "true"},
        headers=auth_headers,
    )
    assert resp.status == 200

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["synType"] is True  # Marker set + files exist -> differential sync allowed


async def test_sync_end_failure_flag_does_not_set_marker(
    client: TestClient,
    auth_headers: dict[str, str],
    storage_root: Path,
    device_client: DeviceClient,
    session_manager: DatabaseSessionManager,
) -> None:
    """A failed synchronous/end must NOT set the init marker.

    The device sends flag="N" when a sync did not complete cleanly.  In that
    case the server must stay in init mode so the device uploads again rather
    than treating any unsynced local files as remote deletions.
    """
    if storage_root.exists():
        shutil.rmtree(str(storage_root))
    storage_root.mkdir(parents=True, exist_ok=True)

    async with session_manager.session() as session:
        await session.execute(delete(UserFileDO))
        await session.commit()

    await device_client.upload_content(
        "Note/test.note", b"content", equipment_no="test"
    )

    # End the sync with a failure flag – marker must NOT be recorded.
    resp = await client.post(
        "/api/file/2/files/synchronous/end",
        json={"equipmentNo": "SN123456", "flag": "N"},
        headers=auth_headers,
    )
    assert resp.status == 200

    resp = await client.post(
        "/api/file/2/files/synchronous/start",
        json={"equipmentNo": "SN123456"},
        headers=auth_headers,
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["synType"] is False  # Failed end -> no marker -> stay in init mode


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
