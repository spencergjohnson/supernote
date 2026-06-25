"""RAG-based chat service for answering questions over notebook content."""

import logging
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.file import UserFileDO
from supernote.server.db.session import DatabaseSessionManager
from supernote.server.services.gemini import GeminiService
from supernote.server.services.search import SearchResult, SearchService
from supernote.server.utils.prompt_loader import PROMPT_LOADER, PromptId

logger = logging.getLogger(__name__)

# Maximum characters of context fed into the prompt.
_MAX_CONTEXT_CHARS = 12_000
# Characters per retrieved chunk snippet.
_MAX_SNIPPET_CHARS = 800


@dataclass
class ChatMessage:
    role: str  # 'user' | 'assistant'
    content: str


@dataclass
class ChatSource:
    file_id: int
    file_name: str
    page_index: int
    text_preview: str
    date: Optional[str]


@dataclass
class ChatAnswer:
    answer: str
    sources: List[ChatSource]


class ChatService:
    """Answers conversational questions by retrieving relevant page chunks and
    calling the LLM with the retrieved context."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        search_service: SearchService,
        gemini_service: GeminiService,
        config: ServerConfig,
    ) -> None:
        self.session_manager = session_manager
        self.search_service = search_service
        self.gemini_service = gemini_service
        self.config = config

    @property
    def is_configured(self) -> bool:
        return self.gemini_service.is_configured

    async def answer(
        self,
        user_id: int,
        query: str,
        messages: List[ChatMessage],
        scope: str = "library",
        top_k: int = 8,
    ) -> ChatAnswer:
        """Answer a question using retrieved notebook context.

        Args:
            user_id: Authenticated user.
            query: The current question.
            messages: Prior conversation turns (most recent last).
            scope: 'library' | 'folder:<id>' | 'note:<id>'.
            top_k: Number of page chunks to retrieve.
        """
        if not self.is_configured:
            return ChatAnswer(
                answer="AI is not configured. Please check your server settings.",
                sources=[],
            )

        file_ids = await self._resolve_scope(user_id, scope)

        chunks = await self.search_service.search_chunks(
            user_id=user_id,
            query=query,
            top_n=top_k,
            file_ids=file_ids,
        )

        if not chunks:
            return ChatAnswer(
                answer="I couldn't find any relevant notes to answer your question. "
                "Make sure your notes have been indexed (OCR + embeddings complete).",
                sources=[],
            )

        system_prompt = PROMPT_LOADER.get_prompt(PromptId.CHAT)
        context_block = self._build_context(chunks)
        history_block = self._build_history(messages)

        full_prompt = (
            f"{system_prompt}\n\n"
            f"{context_block}\n\n"
            f"{history_block}"
            f"User: {query}\nAssistant:"
        )

        try:
            response = await self.gemini_service.generate_content(
                model=self.config.chat_model,
                contents=full_prompt,
            )
            answer_text = (response.text or "").strip()
        except Exception as e:
            logger.error(f"Chat generation failed: {e}", exc_info=True)
            answer_text = "Sorry, I encountered an error generating a response."

        sources = [
            ChatSource(
                file_id=c.file_id,
                file_name=c.file_name,
                page_index=c.page_index,
                text_preview=c.text_preview[:200] if c.text_preview else "",
                date=c.date,
            )
            for c in chunks
        ]

        return ChatAnswer(answer=answer_text, sources=sources)

    async def _resolve_scope(
        self, user_id: int, scope: str
    ) -> Optional[List[int]]:
        """Translate a scope string into a list of file_ids, or None for library-wide."""
        if scope == "library" or not scope:
            return None

        if scope.startswith("note:"):
            try:
                return [int(scope.split(":", 1)[1])]
            except ValueError:
                return None

        if scope.startswith("folder:"):
            try:
                folder_id = int(scope.split(":", 1)[1])
            except ValueError:
                return None
            return await self._files_in_folder(user_id, folder_id)

        return None

    async def _files_in_folder(self, user_id: int, folder_id: int) -> List[int]:
        """Recursively collect .note file ids inside a folder."""
        result: List[int] = []
        stack: List[int] = [folder_id]
        visited: set[int] = set()

        async with self.session_manager.session() as session:
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)

                rows = (
                    (
                        await session.execute(
                            select(UserFileDO.id, UserFileDO.is_folder, UserFileDO.file_name)
                            .where(UserFileDO.user_id == user_id)
                            .where(UserFileDO.directory_id == current)
                            .where(UserFileDO.is_active == "Y")
                        )
                    )
                    .all()
                )
                for fid, is_folder, fname in rows:
                    if is_folder == "Y":
                        stack.append(fid)
                    elif fname.lower().endswith(".note"):
                        result.append(fid)

        return result

    def _build_context(self, chunks: List[SearchResult]) -> str:
        parts: List[str] = []
        total = 0
        for chunk in chunks:
            snippet = (chunk.text_preview or "")[:_MAX_SNIPPET_CHARS]
            header = f"[{chunk.file_name} | Page {chunk.page_index + 1}"
            if chunk.date:
                header += f" | {chunk.date}"
            header += "]"
            entry = f"{header}\n{snippet}"
            if total + len(entry) > _MAX_CONTEXT_CHARS:
                break
            parts.append(entry)
            total += len(entry)
        return "CONTEXT:\n" + "\n\n".join(parts) if parts else ""

    def _build_history(self, messages: List[ChatMessage]) -> str:
        if not messages:
            return ""
        lines: List[str] = []
        for m in messages[-10:]:  # cap prior turns
            role = "User" if m.role == "user" else "Assistant"
            lines.append(f"{role}: {m.content}")
        return "\n".join(lines) + "\n\n"
