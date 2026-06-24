import hashlib
import logging
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)


@dataclass
class BlobMetadata:
    """Metadata for a blob."""

    content_type: str | None = None
    content_md5: str | None = None
    size: int = 0


class BlobStorage(ABC):
    """Interface for Key-Value Blob Storage."""

    @abstractmethod
    async def put(
        self, bucket: str, key: str, stream: AsyncGenerator[bytes, None] | bytes
    ) -> BlobMetadata:
        """Write blob to storage."""
        pass

    @abstractmethod
    def get(
        self, bucket: str, key: str, start: int | None = None, end: int | None = None
    ) -> AsyncGenerator[bytes, None]:
        """Read blob content.

        Args:
            bucket: Bucket name.
            key: Blob key.
            start: Start byte position (inclusive).
            end: End byte position (inclusive).
        """
        pass

    @abstractmethod
    async def delete(self, bucket: str, key: str) -> None:
        """Delete blob."""
        pass

    @abstractmethod
    async def exists(self, bucket: str, key: str) -> bool:
        """Check if blob exists."""
        pass

    @abstractmethod
    async def get_metadata(
        self, bucket: str, key: str, include_md5: bool = False
    ) -> BlobMetadata:
        """Get metadata for a blob.

        Args:
            bucket: Bucket name.
            key: Blob key.
            include_md5: If True, compute and return MD5 checksum.

        Returns:
            BlobMetadata with size and optional content_md5.
        """
        pass

    @abstractmethod
    def get_blob_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob (optional, useful for serving files)."""
        pass

    @abstractmethod
    async def cleanup_temp(self, max_age_seconds: int) -> int:
        """Remove stale temp staging files older than max_age_seconds (by mtime).

        Only removes *.tmp files directly under the temp directory — never
        touches committed blobs. Swallows FileNotFoundError per file (race-safe
        against concurrent uploads completing).

        Returns the count of files removed.
        """
        pass


class LocalBlobStorage(BlobStorage):
    """Local filesystem implementation of Blob Storage.

    Path structure: <root>/<bucket>/<key[0:2]>/<key>
    """

    def __init__(self, storage_root: Path) -> None:
        """Create a local blob storage instance."""
        self.root = storage_root
        self.root.mkdir(parents=True, exist_ok=True)

    def _get_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob."""
        # Clean inputs to prevent traversal
        clean_bucket = Path(bucket).name
        clean_key = Path(key).name
        prefix = clean_key[:2] if len(clean_key) >= 2 else "misc"
        return self.root / clean_bucket / prefix / clean_key

    async def put(
        self, bucket: str, key: str, stream: AsyncGenerator[bytes, None] | bytes
    ) -> BlobMetadata:
        """Write blob to storage."""
        blob_path = self._get_path(bucket, key)
        await aiofiles.os.makedirs(blob_path.parent, exist_ok=True)

        # Write to temp file for atomicity
        temp_dir = self.root / "temp"
        await aiofiles.os.makedirs(temp_dir, exist_ok=True)
        temp_path = temp_dir / f"{secrets.token_hex(8)}.tmp"

        total_size = 0
        md5_hasher = hashlib.md5()

        try:
            async with aiofiles.open(temp_path, "wb") as f:
                if isinstance(stream, bytes):
                    total_size = len(stream)
                    md5_hasher.update(stream)
                    await f.write(stream)
                else:
                    async for chunk in stream:
                        total_size += len(chunk)
                        md5_hasher.update(chunk)
                        await f.write(chunk)

            # Move to final location
            await aiofiles.os.rename(temp_path, blob_path)

            return BlobMetadata(
                content_md5=md5_hasher.hexdigest(),
                size=total_size,
            )

        except Exception:
            if await aiofiles.os.path.exists(temp_path):
                await aiofiles.os.remove(temp_path)
            raise

    async def get(
        self, bucket: str, key: str, start: int | None = None, end: int | None = None
    ) -> AsyncGenerator[bytes, None]:
        """Read blob content."""
        path = self._get_path(bucket, key)
        if not await aiofiles.os.path.exists(path):
            raise FileNotFoundError(f"Blob {bucket}/{key} not found")

        bytes_remaining = None
        if end is not None:
            if start is None:
                start = 0
            bytes_remaining = end - start + 1

        async with aiofiles.open(path, "rb") as f:
            if start is not None and start > 0:
                await f.seek(start)

            while True:
                chunk_size = 8192
                if bytes_remaining is not None:
                    if bytes_remaining <= 0:
                        break
                    chunk_size = min(chunk_size, bytes_remaining)

                chunk = await f.read(chunk_size)
                if not chunk:
                    break

                if bytes_remaining is not None:
                    bytes_remaining -= len(chunk)

                yield chunk

    async def delete(self, bucket: str, key: str) -> None:
        """Delete blob."""
        path = self._get_path(bucket, key)
        if await aiofiles.os.path.exists(path):
            await aiofiles.os.remove(path)

    async def exists(self, bucket: str, key: str) -> bool:
        """Check if blob exists."""
        return bool(await aiofiles.os.path.exists(self._get_path(bucket, key)))

    async def get_metadata(
        self, bucket: str, key: str, include_md5: bool = False
    ) -> BlobMetadata:
        """Get metadata for a blob."""
        path = self._get_path(bucket, key)
        if not await aiofiles.os.path.exists(path):
            raise FileNotFoundError(f"Blob {bucket}/{key} not found")

        stat = await aiofiles.os.stat(path)

        if not include_md5:
            return BlobMetadata(size=stat.st_size)

        # Compute MD5 and size
        md5_hasher = hashlib.md5()
        read_size = 0
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(8192)
                if not chunk:
                    break
                md5_hasher.update(chunk)
                read_size += len(chunk)

        if read_size != stat.st_size:
            # This could happen if file was modified during read
            raise ValueError(
                f"File size changed during read: metadata={stat.st_size}, read={read_size}"
            )

        return BlobMetadata(size=stat.st_size, content_md5=md5_hasher.hexdigest())

    def get_blob_path(self, bucket: str, key: str) -> Path:
        """Get physical path to the blob."""
        return self._get_path(bucket, key)

    async def cleanup_temp(self, max_age_seconds: int) -> int:
        """Remove stale *.tmp staging files older than max_age_seconds (by mtime).

        Safety rules enforced here:
        - Only considers *.tmp files directly under <root>/temp (no recursion).
        - Checks mtime: a file being actively written keeps a fresh mtime and is
          therefore always spared, provided max_age_seconds is comfortably larger
          than the longest plausible upload duration.
        - Swallows FileNotFoundError per file (race-safe: put() may rename the
          file to its final location concurrently).
        """
        temp_dir = self.root / "temp"
        if not await aiofiles.os.path.exists(temp_dir):
            return 0

        try:
            entries = await aiofiles.os.listdir(temp_dir)
        except FileNotFoundError:
            return 0

        now = time.time()
        removed = 0
        for name in entries:
            if not name.endswith(".tmp"):
                continue
            path = temp_dir / name
            try:
                stat_result = await aiofiles.os.stat(path)
                age = now - stat_result.st_mtime
                if age > max_age_seconds:
                    await aiofiles.os.remove(path)
                    removed += 1
                    logger.debug(
                        f"cleanup_temp: removed stale temp file {name} (age={age:.0f}s)"
                    )
            except FileNotFoundError:
                pass  # Completed upload renamed it away — expected, ignore
            except Exception:
                logger.warning(
                    f"cleanup_temp: error processing {path}", exc_info=True
                )
        return removed
