from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from supernote.server.db.base import Base


class AppSettingDO(Base):
    """Durable key-value store for runtime server configuration.

    Persisted model selections (vision, summary, chat, embedding) are stored
    here so they survive restarts and override env/yaml defaults.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, default="")
    update_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<AppSettingDO(key={self.key!r}, value={self.value!r})>"
