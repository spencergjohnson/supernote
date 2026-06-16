"""Local OpenAI-compatible LLM service for supernote-local fork. Author: Spencer Johnson / spencergjohnson.com"""

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from supernote.server.config import ServerConfig

logger = logging.getLogger(__name__)


@dataclass
class LocalGenerateContentResponse:
    """Minimal response object for generate_content; callers use .text."""

    text: str


@dataclass
class LocalEmbedding:
    """Single embedding vector; callers use .values."""

    values: list[float] = field(default_factory=list)


@dataclass
class LocalEmbedContentResponse:
    """Minimal response object for embed_content; callers use .embeddings[0].values."""

    embeddings: list[LocalEmbedding] = field(default_factory=list)


class LocalLLMService:
    """Drop-in replacement for GeminiService backed by an OpenAI-compatible server."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.base_url = config.local_llm_url.rstrip("/")
        self.chat_model = config.local_llm_model
        self.embedding_model = config.local_embedding_model
        self.max_concurrency = config.gemini_max_concurrency
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.config.local_mode and self.base_url)

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy initialization of semaphore to ensure it's in the correct event loop."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        return self._semaphore

    def _build_messages(self, contents: Any) -> list[dict[str, Any]]:
        """Translate supported content shapes into OpenAI chat messages.

        Supported shapes:
          - plain str  -> single text user message
          - list/tuple of strings and PNG bytes -> vision user message
        """
        if isinstance(contents, str):
            return [{"role": "user", "content": contents}]

        if isinstance(contents, (list, tuple)):
            parts: list[dict[str, Any]] = []
            for item in contents:
                if isinstance(item, str):
                    parts.append({"type": "text", "text": item})
                elif isinstance(item, (bytes, bytearray)):
                    b64 = base64.b64encode(bytes(item)).decode("ascii")
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        }
                    )
                else:
                    raise ValueError(
                        f"Unsupported content item type for local LLM: {type(item)!r}"
                    )
            return [{"role": "user", "content": parts}]

        raise ValueError(f"Unsupported contents type for local LLM: {type(contents)!r}")

    async def generate_content(
        self,
        model: str,
        contents: Any,
        config: Any | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LocalGenerateContentResponse:
        """Asynchronously generate content via an OpenAI-compatible chat endpoint."""
        if not self.is_configured:
            raise ValueError("Local LLM not configured")

        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": self._build_messages(contents),
        }

        if response_format is not None:
            payload["response_format"] = response_format
        elif isinstance(config, dict) and config.get("response_mime_type") == "application/json":
            payload["response_format"] = {"type": "json_object"}

        async with self._get_semaphore():
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

        text: str = data["choices"][0]["message"]["content"] or ""
        return LocalGenerateContentResponse(text=text)

    async def embed_content(
        self,
        model: str,
        contents: Any,
        config: Any | None = None,
    ) -> LocalEmbedContentResponse:
        """Asynchronously generate embeddings via an OpenAI-compatible embeddings endpoint."""
        if not self.is_configured:
            raise ValueError("Local LLM not configured")

        payload: dict[str, Any] = {
            "model": self.embedding_model,
            "input": contents,
        }

        async with self._get_semaphore():
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/embeddings",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

        embeddings = [
            LocalEmbedding(values=list(item["embedding"]))
            for item in data.get("data", [])
        ]
        return LocalEmbedContentResponse(embeddings=embeddings)
