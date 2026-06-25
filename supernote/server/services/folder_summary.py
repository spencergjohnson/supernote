"""Service that builds folder-level summaries from child note/folder summaries.

A folder summary is stored as a regular ``SummaryDO`` row whose ``file_id`` is
the folder's id and whose ``data_source`` is ``"FOLDER"``. This means the
existing ``/api/extended/file/summary/list`` endpoint returns it when queried
with a folder id, so no schema change is needed.

Summaries roll up bottom-up: a folder's summary is derived from the overview
summaries of its child notes and the (already generated) summaries of its child
folders. Walking ancestors deepest-first keeps parents consistent with children.
"""

import json
import logging
from typing import Optional

from sqlalchemy import select

from supernote.models.summary import AddSummaryDTO, UpdateSummaryDTO
from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.models.user import UserDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.gemini import GeminiService
from supernote.server.services.processor_modules.summary_common import (
    METADATA_TITLE,
    METADATA_TOPICS,
    _extract_json,
)
from supernote.server.services.summary import SummaryService
from supernote.server.utils.paths import (
    get_folder_summary_id,
    get_overview_id,
    get_summary_id,
)
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

logger = logging.getLogger(__name__)

# Cap the amount of each child summary fed into the prompt to keep context small.
_MAX_CHILD_CHARS = 1500
_MAX_CHILDREN = 60
_ROOT_DIRECTORY_ID = 0


class FolderSummaryService:
    """Generates and maintains folder-level summaries."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        gemini_service: GeminiService,
        summary_service: SummaryService,
        config: ServerConfig,
    ) -> None:
        self.session_manager = session_manager
        self.gemini_service = gemini_service
        self.summary_service = summary_service
        self.config = config

    @property
    def is_configured(self) -> bool:
        return self.gemini_service.is_configured

    async def regenerate_for_folder(
        self, folder_id: int, *, only_missing: bool = False
    ) -> Optional[int]:
        """Regenerate the summary for a single folder.

        Returns the folder's parent ``directory_id`` so callers can walk up the
        tree, or ``None`` if the folder is invalid/not summarizable.
        """
        if not self.is_configured or folder_id == _ROOT_DIRECTORY_ID:
            return None

        async with self.session_manager.session() as session:
            folder = await session.get(UserFileDO, folder_id)
            if (
                not folder
                or folder.is_folder != "Y"
                or folder.is_active != "Y"
            ):
                return None

            user = await session.get(UserDO, folder.user_id)
            if not user or not user.email:
                return None
            user_email = user.email
            parent_id = folder.directory_id
            folder_name = folder.file_name

            children = (
                (
                    await session.execute(
                        select(UserFileDO)
                        .where(UserFileDO.user_id == folder.user_id)
                        .where(UserFileDO.directory_id == folder_id)
                        .where(UserFileDO.is_active == "Y")
                    )
                )
                .scalars()
                .all()
            )
            child_infos = [
                (c.id, c.file_name, c.is_folder, c.storage_key) for c in children
            ]

        folder_uuid = get_folder_summary_id(folder_id)

        if only_missing:
            existing = await self.summary_service.get_summary_by_uuid(
                user_email, folder_uuid
            )
            if existing and existing.content:
                return parent_id

        entries = await self._gather_child_entries(user_email, child_infos)
        if not entries:
            # Nothing meaningful to summarize yet; don't write an empty record.
            return parent_id

        prompt_template = PROMPT_LOADER.get_prompt(PromptId.FOLDER_SUMMARY)
        prompt = (
            f"{prompt_template}\n\nFOLDER NAME: {folder_name}\n\nCHILDREN:\n"
            + "\n\n".join(entries)
        )

        try:
            response = await self.gemini_service.generate_content(
                model=self.config.summary_model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
        except Exception as e:
            logger.error(f"Failed to generate folder summary for {folder_id}: {e}")
            return parent_id

        content_text, metadata_str = self._parse_response(response.text, folder_name)
        if not content_text:
            return parent_id

        await self._upsert_summary(
            user_email,
            AddSummaryDTO(
                file_id=folder_id,
                unique_identifier=folder_uuid,
                content=content_text,
                data_source="FOLDER",
                source_path=folder_name,
                metadata=metadata_str,
            ),
        )
        logger.info(f"Generated folder summary for folder {folder_id} ({folder_name})")
        return parent_id

    async def regenerate_ancestors(
        self, leaf_folder_id: int, *, only_missing: bool = False
    ) -> None:
        """Regenerate a folder and each of its ancestors, bottom-up."""
        if not self.is_configured:
            return
        current: Optional[int] = leaf_folder_id
        visited: set[int] = set()
        while current and current != _ROOT_DIRECTORY_ID and current not in visited:
            visited.add(current)
            current = await self.regenerate_for_folder(current, only_missing=only_missing)

    async def regenerate_all(
        self, user_id: int, *, only_missing: bool = False
    ) -> int:
        """Regenerate summaries for every folder of a user, deepest-first.

        Returns the number of folders processed.
        """
        if not self.is_configured:
            return 0

        async with self.session_manager.session() as session:
            folders = (
                (
                    await session.execute(
                        select(UserFileDO.id, UserFileDO.directory_id)
                        .where(UserFileDO.user_id == user_id)
                        .where(UserFileDO.is_folder == "Y")
                        .where(UserFileDO.is_active == "Y")
                    )
                )
                .all()
            )

        parent_of = {fid: pid for fid, pid in folders}

        def depth(fid: int) -> int:
            d = 0
            cur = fid
            seen: set[int] = set()
            while cur in parent_of and cur not in seen:
                seen.add(cur)
                cur = parent_of[cur]
                d += 1
                if cur == _ROOT_DIRECTORY_ID:
                    break
            return d

        ordered = sorted(parent_of.keys(), key=depth, reverse=True)
        for fid in ordered:
            await self.regenerate_for_folder(fid, only_missing=only_missing)
        return len(ordered)

    async def _gather_child_entries(
        self,
        user_email: str,
        child_infos: list[tuple[int, str, str, Optional[str]]],
    ) -> list[str]:
        entries: list[str] = []
        for cid, cname, is_folder, storage_key in child_infos:
            if len(entries) >= _MAX_CHILDREN:
                break
            content: Optional[str] = None
            if is_folder == "Y":
                summ = await self.summary_service.get_summary_by_uuid(
                    user_email, get_folder_summary_id(cid)
                )
                content = summ.content if summ else None
                kind = "Subfolder"
            else:
                basis = storage_key or str(cid)
                summ = await self.summary_service.get_summary_by_uuid(
                    user_email, get_overview_id(basis)
                )
                if not (summ and summ.content):
                    summ = await self.summary_service.get_summary_by_uuid(
                        user_email, get_summary_id(basis)
                    )
                content = summ.content if summ else None
                kind = "Note"

            if content and content.strip():
                snippet = content.strip()[:_MAX_CHILD_CHARS]
                entries.append(f"### {kind}: {cname}\n{snippet}")
        return entries

    def _parse_response(
        self, text: Optional[str], folder_name: str
    ) -> tuple[Optional[str], Optional[str]]:
        if not text:
            return None, None
        try:
            data = json.loads(_extract_json(text))
        except json.JSONDecodeError:
            # Fall back to a neutral placeholder rather than storing raw JSON.
            logger.warning(
                f"Could not parse folder summary JSON for '{folder_name}'; skipping."
            )
            return None, None

        title = (data.get("title") or "").strip()
        summary = (data.get("summary") or "").strip()
        themes = [str(t).strip() for t in (data.get("themes") or []) if str(t).strip()]

        if not summary and not title:
            return None, None

        content = f"{title}\n\n{summary}".strip() if title else summary
        metadata = json.dumps({METADATA_TITLE: title, METADATA_TOPICS: themes})
        return content, metadata

    async def _upsert_summary(self, user_email: str, dto: AddSummaryDTO) -> None:
        if not dto.unique_identifier:
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
