"""S3 upload worker that watches for new HLS segments and uploads them."""

import logging
import os
import time
from typing import Protocol

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# Content type mapping for HLS files.
CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/MP2T",
}

# Retry configuration for S3 uploads.
MAX_RETRIES = 3
BASE_BACKOFF = 1.0


class S3Client(Protocol):
    """Protocol for S3 upload operations (satisfied by boto3 S3 client)."""

    def upload_file(
        self, Filename: str, Bucket: str, Key: str, ExtraArgs: dict | None = None
    ) -> None: ...


def s3_key_for_file(prefix: str, filename: str) -> str:
    """Build the S3 object key for a given local filename.

    Args:
        prefix: S3 key prefix (e.g. "live").
        filename: Base filename (e.g. "seg_00001.ts").

    Returns:
        Full S3 key (e.g. "live/seg_00001.ts").
    """
    return f"{prefix}/{filename}" if prefix else filename


def content_type_for_file(filename: str) -> str | None:
    """Return the appropriate Content-Type for an HLS file, or None if unknown."""
    _, ext = os.path.splitext(filename)
    return CONTENT_TYPES.get(ext)


def upload_with_retry(
    s3_client: S3Client,
    local_path: str,
    bucket: str,
    key: str,
    max_retries: int = MAX_RETRIES,
    base_backoff: float = BASE_BACKOFF,
) -> bool:
    """Upload a file to S3 with exponential backoff retry.

    Args:
        s3_client: S3 client implementing upload_file.
        local_path: Path to the local file to upload.
        bucket: S3 bucket name.
        key: S3 object key.
        max_retries: Maximum number of retry attempts.
        base_backoff: Base delay in seconds for exponential backoff.

    Returns:
        True if upload succeeded, False if all retries were exhausted.
    """
    content_type = content_type_for_file(os.path.basename(local_path))
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    for attempt in range(max_retries):
        try:
            s3_client.upload_file(
                Filename=local_path,
                Bucket=bucket,
                Key=key,
                ExtraArgs=extra_args if extra_args else None,
            )
            logger.debug("Uploaded %s -> s3://%s/%s", local_path, bucket, key)
            return True
        except Exception:
            delay = base_backoff * (2**attempt)
            logger.warning(
                "Upload failed for %s (attempt %d/%d), retrying in %.1fs",
                local_path,
                attempt + 1,
                max_retries,
                delay,
                exc_info=True,
            )
            time.sleep(delay)

    logger.error("Upload permanently failed for %s after %d attempts", local_path, max_retries)
    return False


class HLSUploadHandler(FileSystemEventHandler):
    """Watchdog handler that uploads new/modified HLS files to S3.

    Monitors a directory for .ts and .m3u8 file events and uploads them
    to the configured S3 bucket with appropriate content types.
    """

    def __init__(self, s3_client: S3Client, bucket: str, prefix: str) -> None:
        super().__init__()
        self.s3_client = s3_client
        self.bucket = bucket
        self.prefix = prefix

    def on_created(self, event: FileCreatedEvent) -> None:
        """Handle new file creation events."""
        if not event.is_directory:
            self._handle_file(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Handle file modification events (for playlist updates)."""
        if not event.is_directory:
            self._handle_file(event.src_path)

    def _handle_file(self, path: str) -> None:
        """Upload a file if it has an HLS-related extension."""
        filename = os.path.basename(path)
        _, ext = os.path.splitext(filename)
        if ext not in CONTENT_TYPES:
            return

        key = s3_key_for_file(self.prefix, filename)
        upload_with_retry(self.s3_client, path, self.bucket, key)


class UploadWorker:
    """Watches a directory for new HLS segments and uploads them to S3.

    Uses watchdog's Observer to monitor the filesystem and trigger uploads
    via HLSUploadHandler.

    Attributes:
        observer: The watchdog Observer instance.
        watch_dir: Directory being monitored.
    """

    def __init__(self, s3_client: S3Client, bucket: str, prefix: str, watch_dir: str) -> None:
        self.watch_dir = watch_dir
        self.handler = HLSUploadHandler(s3_client, bucket, prefix)
        self.observer = Observer()

    def start(self) -> None:
        """Start watching the directory for new files."""
        os.makedirs(self.watch_dir, exist_ok=True)
        self.observer.schedule(self.handler, self.watch_dir, recursive=False)
        self.observer.start()
        logger.info("Upload worker watching %s", self.watch_dir)

    def stop(self) -> None:
        """Stop the directory watcher."""
        self.observer.stop()
        self.observer.join(timeout=10)
        logger.info("Upload worker stopped")
