"""Durable key-value settings service backed by the app_settings table.

Persisted model selections survive restarts and override env/yaml defaults.
All call sites already read ``config.<role>_model`` per call (Phase B.2), so
mutating the shared ``ServerConfig`` instance is enough to take effect without
restarting any service.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import select

from supernote.server.config import ServerConfig
from supernote.server.db.models.settings import AppSettingDO
from supernote.server.db.session import DatabaseSessionManager

logger = logging.getLogger(__name__)

# Keys stored in app_settings for each model role.
KEY_VISION_MODEL = "model.vision"
KEY_SUMMARY_MODEL = "model.summary"
KEY_CHAT_MODEL = "model.chat"
KEY_EMBEDDING_MODEL = "model.embedding"

_ROLE_KEYS = {
    "vision": KEY_VISION_MODEL,
    "summary": KEY_SUMMARY_MODEL,
    "chat": KEY_CHAT_MODEL,
    "embedding": KEY_EMBEDDING_MODEL,
}


class SettingsService:
    """CRUD wrapper around the app_settings table."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    async def get(self, key: str) -> Optional[str]:
        async with self.session_manager.session() as session:
            row = await session.get(AppSettingDO, key)
            return row.value if row else None

    async def set(self, key: str, value: str) -> None:
        async with self.session_manager.session() as session:
            row = await session.get(AppSettingDO, key)
            if row:
                row.value = value
                row.update_time = datetime.now(timezone.utc)
            else:
                session.add(AppSettingDO(key=key, value=value))
            await session.commit()

    async def get_all(self) -> Dict[str, str]:
        async with self.session_manager.session() as session:
            rows = (await session.execute(select(AppSettingDO))).scalars().all()
            return {r.key: r.value for r in rows}

    async def apply_to_config(self, config: ServerConfig) -> None:
        """Overwrite config role fields with any persisted values.

        Called at startup after migrations so DB wins over env/yaml.

        - vision / embedding: only applied when the stored value is non-empty
          (a missing or empty value means "use the env/yaml default").
        - summary / chat: applied whenever the key *exists* in the DB, even
          when its value is empty — an empty string is a valid sentinel meaning
          "inherit from the fallback chain" and must survive restarts.
        """
        stored = await self.get_all()

        if v := stored.get(KEY_VISION_MODEL):
            logger.info(f"Settings: override vision model -> {v!r}")
            config.local_llm_model = v

        if KEY_SUMMARY_MODEL in stored:
            v = stored[KEY_SUMMARY_MODEL]
            logger.info(f"Settings: override summary model -> {v!r}")
            config.local_summary_model = v

        if KEY_CHAT_MODEL in stored:
            v = stored[KEY_CHAT_MODEL]
            logger.info(f"Settings: override chat model -> {v!r}")
            config.local_chat_model = v

        if v := stored.get(KEY_EMBEDDING_MODEL):
            logger.info(f"Settings: override embedding model -> {v!r}")
            config.local_embedding_model = v

    async def set_role_model(self, role: str, model_id: str) -> None:
        """Persist a model selection for a named role and return.

        The caller is responsible for also mutating ``config`` if the change
        should take effect immediately.
        """
        key = _ROLE_KEYS.get(role)
        if not key:
            raise ValueError(f"Unknown model role: {role!r}")
        await self.set(key, model_id)

    def current_role_models(self, config: ServerConfig) -> Dict[str, str]:
        """Return the active model id for each role from the live config."""
        return {
            "vision": config.vision_model,
            "summary": config.summary_model,
            "chat": config.chat_model,
            "embedding": config.embedding_model_name,
        }
