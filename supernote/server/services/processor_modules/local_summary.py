import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from supernote.models.summary import (
    AddSummaryDTO,
    UpdateSummaryDTO,
)
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.note_processing import NotePageContentDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.file import FileService
from supernote.server.services.local_llm_service import LocalLLMService
from supernote.server.services.processor_modules import ProcessorModule
from supernote.server.services.processor_modules.summary_common import (
    build_transcript_text,
    parse_summary_response,
)
from supernote.server.services.summary import SummaryService
from supernote.server.utils.paths import (
    get_overview_id,
    get_summary_id,
    get_transcript_id,
)
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

logger = logging.getLogger(__name__)


class LocalSummaryModule(ProcessorModule):
    """Module responsible for aggregating OCR text and generating summaries for a note."""

    def __init__(
        self,
        file_service: FileService,
        config: ServerConfig,
        llm_service: LocalLLMService,
        summary_service: SummaryService,
    ) -> None:
        self.file_service = file_service
        self.config = config
        self.llm_service = llm_service
        self.summary_service = summary_service

    @property
    def name(self) -> str:
        return "LocalSummaryModule"

    @property
    def task_type(self) -> str:
        return "SUMMARY_GENERATION"

    async def run_if_needed(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
    ) -> bool:
        """Determines if summary generation is needed."""
        # Summary is a file-level task (global), not page-level.
        if page_index is not None:
            return False

        if not self.llm_service.is_configured:
            return False

        if not await super().run_if_needed(file_id, session_manager, page_index):
            return False

        return True

    async def process(
        self,
        file_id: int,
        session_manager: DatabaseSessionManager,
        page_index: Optional[int] = None,
        page_id: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        """
        Generates an AI summary for the given file.

        1. Aggregates all OCR text for the file.
        2. Sends to the local LLM for summarization and date extraction.
        3. Stores the result as a new Summary.
        """
        logger.info(f"Starting summary generation for file_id={file_id}")

        async with session_manager.session() as session:
            # 1. Fetch File Info
            file_do = await session.get(UserFileDO, file_id)
            if not file_do:
                logger.error(f"File {file_id} not found.")
                return

            user: Optional[UserDO] = await session.get(UserDO, file_do.user_id)
            if not user or not user.email:
                logger.error(f"User for file {file_id} not found.")
                return
            user_email = user.email

            # 2. Key Generation
            file_basis = file_do.storage_key or str(file_do.id)
            summary_uuid = get_summary_id(file_basis)
            transcript_uuid = get_transcript_id(file_basis)
            overview_uuid = get_overview_id(file_basis)

            # 3. Aggregate OCR Text
            # We want to format the text with page markers so the model can cite them.
            stmt = (
                select(NotePageContentDO)
                .where(NotePageContentDO.file_id == file_id)
                .order_by(NotePageContentDO.page_index)
            )
            result = await session.execute(stmt)
            pages = result.scalars().all()

        if not pages:
            logger.info(f"No OCR pages found for file {file_id}. Skipping summary.")
            return

        # Format transcript with Page markers and inferred dates
        full_text = build_transcript_text(pages, file_do)

        # 4. Generate Transcript Summary (Preserve existing functionality)
        # Store the raw aggregated text as a 'transcript' summary type first
        # This is a good baseline to have.
        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=transcript_uuid,
                content=full_text,
                data_source="OCR",
                source_path=file_do.file_name,
            ),
        )

        # 5. Generate AI Summary using local LLM
        # Determine prompt based on filename/type
        custom_type = Path(file_do.file_name).stem.lower()

        # Load Prompt using specialized logic: Common + (Custom OR Default)
        prompt_template = PROMPT_LOADER.get_prompt(
            PromptId.SUMMARY_GENERATION, custom_type=custom_type
        )
        prompt = f"{prompt_template}\n\nTRANSCRIPT:\n{full_text}"

        try:
            response = await self.llm_service.generate_content(
                model=self.config.summary_model,
                contents=prompt,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.error(f"Failed to generate AI summary for file {file_id}: {e}")
            return

        parsed = parse_summary_response(response.text, file_id)

        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=file_id,
                unique_identifier=summary_uuid,
                content=parsed.segments_markdown,
                data_source="GEMINI",
                source_path=file_do.file_name,
                metadata=parsed.segments_metadata,
            ),
        )

        # Overarching note overview (single high-level summary of the whole note).
        if parsed.overview_content:
            await self._upsert_summary(
                user_email,
                AddSummaryDTO(
                    file_id=file_id,
                    unique_identifier=overview_uuid,
                    content=parsed.overview_content,
                    data_source="OVERVIEW",
                    source_path=file_do.file_name,
                    metadata=parsed.overview_metadata,
                ),
            )

    async def _upsert_summary(self, user_email: str, dto: AddSummaryDTO) -> None:
        """Helper to either add or update a summary based on its unique identifier."""
        if not dto.unique_identifier:
            logger.error("Cannot upsert summary without a unique identifier")
            return

        existing = await self.summary_service.get_summary_by_uuid(
            user_email, dto.unique_identifier
        )
        if existing and existing.id is not None:
            await self.summary_service.update_summary(
                user_email,
                UpdateSummaryDTO(
                    id=existing.id,
                    content=dto.content,
                    data_source=dto.data_source,
                    source_path=dto.source_path,
                    metadata=dto.metadata,
                ),
            )
        else:
            await self.summary_service.add_summary(user_email, dto)
