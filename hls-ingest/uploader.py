"""S3 upload worker that watches for completed HLS files and uploads them.

Uses watchdog's FileClosedEvent (inotify IN_CLOSE_WRITE) for segments and
FileMovedEvent (inotify IN_MOVED_TO) for playlists. ffmpeg writes playlists
via atomic rename (.tmp -> .m3u8), so they arrive as move events, not close
events. Uploads run in a separate worker thread to avoid blocking the
observer. Playlists are deferred until the queue drains, ensuring segments
reach S3 before the playlist references them.
"""

import logging
import os
import queue
import threading
import time
from typing import Protocol

from watchdog.events import FileClosedEvent, FileMovedEvent, FileSystemEventHandler
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

# Default seconds to wait for more segments before uploading a deferred playlist.
DEFAULT_PLAYLIST_DEFER_SECS = 2.0


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
    """Watchdog handler that enqueues completed HLS files for upload.

    Responds to on_closed (FileClosedEvent) for segments written directly by
    ffmpeg, and on_moved (FileMovedEvent) for playlists that ffmpeg updates
    via atomic rename. Both require inotify (Linux); the production Docker
    container runs on Linux.
    """

    def __init__(self, upload_queue: queue.Queue) -> None:
        super().__init__()
        self._queue = upload_queue

    def on_closed(self, event: FileClosedEvent) -> None:
        """Enqueue HLS files when they are closed after writing."""
        if event.is_directory:
            return
        self._enqueue_if_hls(event.src_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        """Enqueue HLS files that arrive via atomic rename.

        ffmpeg updates playlists by writing to a temp file then renaming
        it. inotify delivers this as IN_MOVED_TO, not IN_CLOSE_WRITE.
        """
        if event.is_directory:
            return
        self._enqueue_if_hls(event.dest_path)

    def _enqueue_if_hls(self, path: str) -> None:
        filename = os.path.basename(path)
        _, ext = os.path.splitext(filename)
        if ext in CONTENT_TYPES:
            self._queue.put(path)


class UploadWorkerThread:
    """Drains an upload queue, uploading segments immediately and deferring playlists.

    Segments (.ts) are uploaded as soon as they are dequeued. Playlists (.m3u8)
    are held back until no new items arrive for ``playlist_defer_secs``, ensuring
    segments reach S3 before the playlist references them.

    A None sentinel in the queue signals the thread to stop.
    """

    def __init__(
        self,
        s3_client: S3Client,
        bucket: str,
        prefix: str,
        upload_queue: queue.Queue,
        playlist_defer_secs: float = DEFAULT_PLAYLIST_DEFER_SECS,
    ) -> None:
        self.s3_client = s3_client
        self.bucket = bucket
        self.prefix = prefix
        self._queue = upload_queue
        self._playlist_defer_secs = playlist_defer_secs

    def run(self) -> None:
        """Process the upload queue until a None sentinel is received."""
        deferred_playlist: str | None = None

        while True:
            timeout = self._playlist_defer_secs if deferred_playlist else None
            try:
                path = self._queue.get(timeout=timeout)
            except queue.Empty:
                # Timeout expired — upload the deferred playlist now
                if deferred_playlist:
                    self._upload(deferred_playlist)
                    deferred_playlist = None
                continue

            if path is None:
                # Sentinel: upload any remaining deferred playlist, then exit
                if deferred_playlist:
                    self._upload(deferred_playlist)
                break

            _, ext = os.path.splitext(path)
            if ext == ".m3u8":
                # Defer playlist; upload any previously deferred one first
                if deferred_playlist:
                    self._upload(deferred_playlist)
                deferred_playlist = path
            else:
                self._upload(path)

    def _upload(self, path: str) -> None:
        """Upload a single file to S3."""
        filename = os.path.basename(path)
        key = s3_key_for_file(self.prefix, filename)
        upload_with_retry(self.s3_client, path, self.bucket, key)


class UploadWorker:
    """Watches a directory for completed HLS files and uploads them to S3.

    Uses watchdog's Observer to detect file close events and a separate
    thread to perform uploads, ensuring retries don't block event dispatch.
    """

    def __init__(self, s3_client: S3Client, bucket: str, prefix: str, watch_dir: str) -> None:
        self.watch_dir = watch_dir
        self._queue: queue.Queue = queue.Queue()
        self.handler = HLSUploadHandler(self._queue)
        self._worker = UploadWorkerThread(s3_client, bucket, prefix, self._queue)
        self.observer = Observer()
        self._upload_thread = threading.Thread(target=self._worker.run, daemon=True)

    def start(self) -> None:
        """Start watching the directory and uploading files."""
        os.makedirs(self.watch_dir, exist_ok=True)
        self.observer.schedule(self.handler, self.watch_dir, recursive=False)
        self.observer.start()
        self._upload_thread.start()
        logger.info("Upload worker watching %s", self.watch_dir)

    def stop(self) -> None:
        """Stop the directory watcher and upload thread."""
        self.observer.stop()
        self.observer.join(timeout=10)
        self._queue.put(None)  # sentinel to stop worker thread
        self._upload_thread.join(timeout=10)
        logger.info("Upload worker stopped")
