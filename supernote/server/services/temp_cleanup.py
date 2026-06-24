"""Background service that periodically sweeps stale temp upload files."""

import asyncio
import logging

from .blob import BlobStorage

logger = logging.getLogger(__name__)


class TempCleanupService:
    """Periodically removes orphaned *.tmp staging files from blob storage.

    Uses the mtime of each file as the age gate, so any upload currently in
    progress (which keeps a fresh mtime) is always spared.
    """

    def __init__(
        self,
        blob_storage: BlobStorage,
        ttl_seconds: int = 3600,
        interval_seconds: int = 900,
    ) -> None:
        self.blob_storage = blob_storage
        self.ttl_seconds = ttl_seconds
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        """Start the background sweep loop."""
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._loop(), name="temp-cleanup")
        logger.info(
            f"TempCleanupService started (ttl={self.ttl_seconds}s, "
            f"interval={self.interval_seconds}s)"
        )

    async def stop(self) -> None:
        """Signal shutdown and wait for the loop to exit."""
        self._shutdown_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TempCleanupService stopped.")

    async def _loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                removed = await self.blob_storage.cleanup_temp(self.ttl_seconds)
                if removed:
                    logger.info(f"TempCleanup: removed {removed} stale temp file(s)")
            except Exception:
                logger.warning("TempCleanup: error during sweep", exc_info=True)

            # Sleep for the interval, but wake immediately on shutdown.
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=self.interval_seconds
                )
            except asyncio.TimeoutError:
                pass
