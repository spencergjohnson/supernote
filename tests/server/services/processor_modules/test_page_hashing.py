from pathlib import Path

import pytest
from sqlalchemy import select

from supernote.models.base import ProcessingStatus
from supernote.server.constants import USER_DATA_BUCKET
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO, SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.blob import BlobStorage
from supernote.server.services.file import FileService
from supernote.server.services.processor_modules.page_hashing import PageHashingModule


@pytest.fixture
def page_hashing_module(file_service: FileService) -> PageHashingModule:
    return PageHashingModule(file_service=file_service)


async def test_process_with_real_file(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """Integration test using a real .note file and real FileService."""

    # Setup Data
    user_id = 100
    file_id = 999
    storage_key = "test_note_storage_key"

    # Read real test file
    if not test_note_path.exists():
        pytest.skip(f"Test file not found at {test_note_path}")

    file_content = test_note_path.read_bytes()

    # Write to Blob Storage
    await blob_storage.put(USER_DATA_BUCKET, storage_key, file_content)

    async with session_manager.session() as session:
        user_file = UserFileDO(
            id=file_id,
            user_id=user_id,
            storage_key=storage_key,
            file_name="real.note",
            directory_id=0,
        )
        session.add(user_file)
        await session.commit()

    # Run module lifecycle (Real Parser, Real File)
    await page_hashing_module.run(file_id, session_manager)

    # Assertions
    async with session_manager.session() as session:
        # Check Pages
        pages = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .order_by(NotePageContentDO.page_index)
                )
            )
            .scalars()
            .all()
        )

        # We don't know exactly how many pages, but it should be > 0
        print(f"Found {len(pages)} pages")
        assert len(pages) > 0

        first_page = pages[0]
        assert first_page is not None
        assert first_page.content_hash is not None
        assert len(first_page.content_hash) > 0

        # Capture the hash to verify change detection later
        original_hash = first_page.content_hash

        # Check Task
        task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "HASHING")
                )
            )
            .scalars()
            .first()
        )

        assert task is not None
        assert task.status == "COMPLETED"

    # Test Change Detection (Simulated)
    # Since we can't easily edit the binary .note file to change content,
    # we will Simulate a change by manually modifying the DB hash to be wrong.
    # Then running process again should revert it to the correct hash.

    async with session_manager.session() as session:
        page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == 0)
                )
            )
            .scalars()
            .first()
        )

        assert page is not None
        page.content_hash = "FAKE_HASH"
        # Set some dummy content that should be cleared
        page.text_content = "dummy_ocr"

        # Add a mock downstream task that should be invalidated (deleted)
        ocr_task = SystemTaskDO(
            file_id=file_id,
            task_type="OCR_EXTRACTION",
            key=f"page_{page.page_id}",
            status="COMPLETED",
        )
        session.add(ocr_task)
        await session.commit()

    # Run process again
    await page_hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == 0)
                )
            )
            .scalars()
            .first()
        )

        assert page is not None
        # Hash should be back to original (real) hash
        assert page.content_hash == original_hash
        # Text content should be cleared because we simulated a "change" (Fake -> Real)
        assert page.text_content is None

        # Check that the downstream task was invalidated (deleted)
        invalidated_task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "OCR_EXTRACTION")
                    .where(SystemTaskDO.key == f"page_{page.page_id}")
                )
            )
            .scalars()
            .first()
        )
        assert invalidated_task is None

    # Test Deletion
    # We will simulate deletion by manually adding an extra page that doesn't exist in the file.
    # The process should remove it.

    extra_page_index = len(pages) + 5  # Safely out of bounds
    async with session_manager.session() as session:
        extra_page = NotePageContentDO(
            file_id=file_id,
            page_index=extra_page_index,
            page_id="trash_id",
            content_hash="trash",
        )
        session.add(extra_page)
        await session.commit()

    # Run process again
    await page_hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        # Verify extra page is gone
        missing_page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == extra_page_index)
                )
            )
            .scalars()
            .first()
        )

        assert missing_page is None

        # Verify original pages still there
        current_pages = (
            (
                await session.execute(
                    select(NotePageContentDO).where(
                        NotePageContentDO.file_id == file_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(current_pages) == len(pages)


async def test_summary_task_invalidated_on_page_change(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """When a page's content changes, the SUMMARY_GENERATION/global task must be deleted.

    This ensures that the SummaryModule re-runs in the same pipeline pass
    and generates a fresh summary from the updated OCR text.
    """
    if not test_note_path.exists():
        pytest.skip(f"Test file not found at {test_note_path}")

    file_id = 1100
    storage_key = "summary_invalidation_key"

    file_content = test_note_path.read_bytes()
    await blob_storage.put(USER_DATA_BUCKET, storage_key, file_content)

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=200,
                storage_key=storage_key,
                file_name="invalidation_test.note",
                directory_id=0,
            )
        )
        await session.commit()

    # First run — populates pages and marks HASHING COMPLETED.
    await page_hashing_module.run(file_id, session_manager)

    # Plant a completed SUMMARY_GENERATION/global task to simulate a prior summary run.
    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(
                file_id=file_id,
                task_type="SUMMARY_GENERATION",
                key="global",
                status=ProcessingStatus.COMPLETED,
            )
        )
        # Corrupt the first page's hash so the next run detects a content change.
        page = (
            (
                await session.execute(
                    select(NotePageContentDO)
                    .where(NotePageContentDO.file_id == file_id)
                    .where(NotePageContentDO.page_index == 0)
                )
            )
            .scalars()
            .first()
        )
        assert page is not None
        page.content_hash = "STALE_HASH"
        await session.commit()

    # Second run — hash mismatch should trigger summary invalidation.
    await page_hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        summary_task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert summary_task is None, (
            "SUMMARY_GENERATION/global task should be deleted when page content changes"
        )


async def test_summary_task_not_invalidated_when_unchanged(
    page_hashing_module: PageHashingModule,
    session_manager: DatabaseSessionManager,
    blob_storage: BlobStorage,
    test_note_path: Path,
) -> None:
    """When no page content changes, the SUMMARY_GENERATION task is left intact."""
    if not test_note_path.exists():
        pytest.skip(f"Test file not found at {test_note_path}")

    file_id = 1101
    storage_key = "summary_no_invalidation_key"

    file_content = test_note_path.read_bytes()
    await blob_storage.put(USER_DATA_BUCKET, storage_key, file_content)

    async with session_manager.session() as session:
        session.add(
            UserFileDO(
                id=file_id,
                user_id=201,
                storage_key=storage_key,
                file_name="no_invalidation_test.note",
                directory_id=0,
            )
        )
        await session.commit()

    # First run — correct hashes, no change.
    await page_hashing_module.run(file_id, session_manager)

    # Plant a completed summary task.
    async with session_manager.session() as session:
        session.add(
            SystemTaskDO(
                file_id=file_id,
                task_type="SUMMARY_GENERATION",
                key="global",
                status=ProcessingStatus.COMPLETED,
            )
        )
        await session.commit()

    # Second run with unchanged file — no content change, summary task should survive.
    await page_hashing_module.process(file_id, session_manager)

    async with session_manager.session() as session:
        summary_task = (
            (
                await session.execute(
                    select(SystemTaskDO)
                    .where(SystemTaskDO.file_id == file_id)
                    .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                    .where(SystemTaskDO.key == "global")
                )
            )
            .scalars()
            .first()
        )
        assert summary_task is not None, (
            "SUMMARY_GENERATION/global task should be preserved when nothing changed"
        )
        assert summary_task.status == ProcessingStatus.COMPLETED
