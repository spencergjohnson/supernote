"""One-time backfill of note overviews and folder summaries.

This regenerates the new summary artifacts from the OCR text that already
exists in the database. It never re-runs OCR, PNG conversion, or embeddings, so
running it is cheap relative to the original indexing pipeline.

It is idempotent and gap-filling: note overviews are only generated for notes
that were summarized before the overview feature existed, and folder summaries
are only generated for folders that don't have one yet.
"""

import asyncio
import logging

from sqlalchemy import and_, distinct, select

from supernote.models.base import ProcessingStatus
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.models.summary import SummaryDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.folder_summary import FolderSummaryService
from supernote.server.services.processor_modules import ProcessorModule

logger = logging.getLogger(__name__)

# Pause between consecutive note-overview regenerations at startup.
# Keeps the local LLM from being hit with a burst of concurrent requests when
# the library is large.  0.5 s is imperceptible for the user but gives the
# inference server breathing room between calls.
_BACKFILL_DELAY_SECONDS = 0.5


class BackfillService:
    """Fills in note overviews and folder summaries for pre-existing data."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        summary_module: ProcessorModule,
        folder_summary_service: FolderSummaryService,
    ) -> None:
        self.session_manager = session_manager
        self.summary_module = summary_module
        self.folder_summary_service = folder_summary_service

    async def run(self) -> None:
        """Run the full backfill: note overviews first, then folder summaries."""
        if not self.folder_summary_service.is_configured:
            logger.info("Backfill skipped: LLM not configured.")
            return
        try:
            n_notes = await self.backfill_note_overviews()
            logger.info(f"Backfill: regenerated overviews for {n_notes} note(s).")
        except Exception as e:
            logger.error(f"Note overview backfill failed: {e}", exc_info=True)

        try:
            n_folders = await self.backfill_folder_summaries()
            logger.info(f"Backfill: generated {n_folders} folder summary(ies).")
        except Exception as e:
            logger.error(f"Folder summary backfill failed: {e}", exc_info=True)

    async def backfill_note_overviews(self) -> int:
        """Generate overviews for already-summarized notes that lack one."""
        async with self.session_manager.session() as session:
            # Notes whose summary pipeline already completed at least once.
            completed_stmt = (
                select(distinct(SystemTaskDO.file_id))
                .where(SystemTaskDO.task_type == "SUMMARY_GENERATION")
                .where(SystemTaskDO.key == "global")
                .where(SystemTaskDO.status == ProcessingStatus.COMPLETED)
            )
            completed_ids = set((await session.execute(completed_stmt)).scalars().all())

            # Notes that already have an overview row.
            has_overview_stmt = (
                select(distinct(SummaryDO.file_id))
                .where(SummaryDO.data_source == "OVERVIEW")
                .where(SummaryDO.is_deleted.is_(False))
            )
            has_overview = set(
                (await session.execute(has_overview_stmt)).scalars().all()
            )

            candidate_ids = completed_ids - has_overview
            if not candidate_ids:
                return 0

            # Restrict to currently-active .note files.
            active_stmt = (
                select(UserFileDO.id)
                .where(UserFileDO.id.in_(candidate_ids))
                .where(UserFileDO.is_active == "Y")
                .where(UserFileDO.is_folder == "N")
                .where(UserFileDO.file_name.ilike("%.note"))
            )
            target_ids = list((await session.execute(active_stmt)).scalars().all())

        count = 0
        for file_id in target_ids:
            try:
                # We call process() directly rather than run() because run()
                # checks run_if_needed(), which returns False for notes whose
                # SUMMARY_GENERATION task is already COMPLETED — exactly the
                # set we are targeting here (notes that have a summary but lack
                # the newer OVERVIEW artifact).  Calling process() bypasses that
                # gate while keeping the failure-safe retry-on-next-startup
                # behaviour (a crash here leaves the COMPLETED status intact).
                await self.summary_module.process(file_id, self.session_manager)
                count += 1
            except Exception as e:
                logger.warning(f"Overview backfill failed for file {file_id}: {e}")
            # Pace LLM calls so a large library doesn't flood the inference server
            # at startup.  Backfill already runs in the background, so this only
            # slows down the background task, not the main server.
            await asyncio.sleep(_BACKFILL_DELAY_SECONDS)
        return count

    async def backfill_folder_summaries(self) -> int:
        """Generate folder summaries for folders that don't have one."""
        async with self.session_manager.session() as session:
            user_ids = list(
                (
                    await session.execute(
                        select(distinct(UserFileDO.user_id)).where(
                            and_(
                                UserFileDO.is_folder == "Y",
                                UserFileDO.is_active == "Y",
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )

        total = 0
        for user_id in user_ids:
            try:
                total += await self.folder_summary_service.regenerate_all(
                    user_id, only_missing=True
                )
            except Exception as e:
                logger.warning(f"Folder backfill failed for user {user_id}: {e}")
        return total
