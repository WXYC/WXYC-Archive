"""Tests for S3 uploads: segment detection, retry logic, content types, ordering."""

import os
import queue
from unittest.mock import MagicMock, call, patch

from watchdog.events import FileClosedEvent, FileMovedEvent, FileSystemEventHandler

from uploader import (
    HLSUploadHandler,
    UploadWorkerThread,
    content_type_for_file,
    s3_key_for_file,
    upload_with_retry,
)


class TestS3KeyForFile:
    """Tests for S3 key construction."""

    def test_with_prefix(self):
        assert s3_key_for_file("live", "seg_00001.ts") == "live/seg_00001.ts"

    def test_with_empty_prefix(self):
        assert s3_key_for_file("", "seg_00001.ts") == "seg_00001.ts"

    def test_playlist_key(self):
        assert s3_key_for_file("live", "live.m3u8") == "live/live.m3u8"


class TestContentTypeForFile:
    """Tests for content type detection."""

    def test_ts_file(self):
        assert content_type_for_file("seg_00001.ts") == "video/MP2T"

    def test_m3u8_file(self):
        assert content_type_for_file("live.m3u8") == "application/vnd.apple.mpegurl"

    def test_unknown_extension(self):
        assert content_type_for_file("readme.txt") is None

    def test_no_extension(self):
        assert content_type_for_file("Makefile") is None


class TestUploadWithRetry:
    """Tests for the upload retry mechanism."""

    @patch("uploader.time.sleep")
    def test_successful_upload_on_first_try(self, mock_sleep):
        mock_client = MagicMock()
        result = upload_with_retry(mock_client, "/tmp/seg.ts", "bucket", "live/seg.ts")
        assert result is True
        mock_client.upload_file.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("uploader.time.sleep")
    def test_retry_on_failure_then_succeed(self, mock_sleep):
        mock_client = MagicMock()
        mock_client.upload_file.side_effect = [Exception("network error"), None]

        result = upload_with_retry(mock_client, "/tmp/seg.ts", "bucket", "live/seg.ts")
        assert result is True
        assert mock_client.upload_file.call_count == 2
        mock_sleep.assert_called_once()

    @patch("uploader.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep):
        mock_client = MagicMock()
        mock_client.upload_file.side_effect = Exception("persistent error")

        result = upload_with_retry(
            mock_client, "/tmp/seg.ts", "bucket", "live/seg.ts", max_retries=3
        )
        assert result is False
        assert mock_client.upload_file.call_count == 3

    @patch("uploader.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        mock_client = MagicMock()
        mock_client.upload_file.side_effect = Exception("fail")

        upload_with_retry(
            mock_client,
            "/tmp/seg.ts",
            "bucket",
            "live/seg.ts",
            max_retries=3,
            base_backoff=1.0,
        )

        assert mock_sleep.call_args_list == [call(1.0), call(2.0), call(4.0)]

    @patch("uploader.time.sleep")
    def test_ts_file_gets_content_type(self, mock_sleep):
        mock_client = MagicMock()
        upload_with_retry(mock_client, "/tmp/seg_00001.ts", "bucket", "live/seg_00001.ts")

        _, kwargs = mock_client.upload_file.call_args
        assert kwargs["ExtraArgs"]["ContentType"] == "video/MP2T"

    @patch("uploader.time.sleep")
    def test_m3u8_file_gets_content_type(self, mock_sleep):
        mock_client = MagicMock()
        upload_with_retry(mock_client, "/tmp/live.m3u8", "bucket", "live/live.m3u8")

        _, kwargs = mock_client.upload_file.call_args
        assert kwargs["ExtraArgs"]["ContentType"] == "application/vnd.apple.mpegurl"

    @patch("uploader.time.sleep")
    def test_unknown_file_no_extra_args(self, mock_sleep):
        mock_client = MagicMock()
        upload_with_retry(mock_client, "/tmp/readme.txt", "bucket", "live/readme.txt")

        _, kwargs = mock_client.upload_file.call_args
        assert kwargs["ExtraArgs"] is None


class TestHLSUploadHandlerOnClosed:
    """Tests that the handler uses on_closed and enqueues paths."""

    def test_on_closed_enqueues_ts_file(self, tmp_output_dir):
        q = queue.Queue()
        handler = HLSUploadHandler(q)

        ts_path = os.path.join(tmp_output_dir, "seg_00001.ts")
        with open(ts_path, "wb") as f:
            f.write(b"\x00" * 100)

        event = FileClosedEvent(ts_path)
        handler.on_closed(event)

        assert not q.empty()
        assert q.get_nowait() == ts_path

    def test_on_closed_enqueues_m3u8_file(self, tmp_output_dir):
        q = queue.Queue()
        handler = HLSUploadHandler(q)

        m3u8_path = os.path.join(tmp_output_dir, "live.m3u8")
        with open(m3u8_path, "w") as f:
            f.write("#EXTM3U\n")

        event = FileClosedEvent(m3u8_path)
        handler.on_closed(event)

        assert not q.empty()
        assert q.get_nowait() == m3u8_path

    def test_on_closed_ignores_non_hls_files(self, tmp_output_dir):
        q = queue.Queue()
        handler = HLSUploadHandler(q)

        txt_path = os.path.join(tmp_output_dir, "notes.txt")
        with open(txt_path, "w") as f:
            f.write("hello")

        event = FileClosedEvent(txt_path)
        handler.on_closed(event)

        assert q.empty()

    def test_on_moved_enqueues_dest_m3u8(self, tmp_output_dir):
        """ffmpeg updates playlists via atomic rename (.tmp -> .m3u8).

        inotify delivers this as IN_MOVED_TO (FileMovedEvent), not
        IN_CLOSE_WRITE (FileClosedEvent). The handler must enqueue the
        destination path when it has an HLS extension.
        """
        q = queue.Queue()
        handler = HLSUploadHandler(q)

        src = os.path.join(tmp_output_dir, "live.m3u8.tmp")
        dest = os.path.join(tmp_output_dir, "live.m3u8")
        with open(dest, "w") as f:
            f.write("#EXTM3U\n")

        event = FileMovedEvent(src, dest)
        handler.on_moved(event)

        assert not q.empty()
        assert q.get_nowait() == dest

    def test_on_moved_ignores_non_hls_dest(self, tmp_output_dir):
        q = queue.Queue()
        handler = HLSUploadHandler(q)

        src = os.path.join(tmp_output_dir, "data.tmp")
        dest = os.path.join(tmp_output_dir, "data.txt")

        event = FileMovedEvent(src, dest)
        handler.on_moved(event)

        assert q.empty()

    def test_handler_does_not_override_on_created(self):
        q = queue.Queue()
        handler = HLSUploadHandler(q)
        assert type(handler).on_created is FileSystemEventHandler.on_created

    def test_handler_does_not_override_on_modified(self):
        q = queue.Queue()
        handler = HLSUploadHandler(q)
        assert type(handler).on_modified is FileSystemEventHandler.on_modified


class TestUploadWorkerThread:
    """Tests for the queue-based upload worker thread."""

    @patch("uploader.upload_with_retry")
    def test_processes_ts_file_immediately(self, mock_upload, tmp_output_dir):
        q = queue.Queue()
        mock_s3 = MagicMock()
        worker = UploadWorkerThread(mock_s3, "bucket", "live", q)

        ts_path = os.path.join(tmp_output_dir, "seg_00001.ts")
        with open(ts_path, "wb") as f:
            f.write(b"\x00" * 100)

        q.put(ts_path)
        q.put(None)  # sentinel

        worker.run()

        mock_upload.assert_called_once_with(mock_s3, ts_path, "bucket", "live/seg_00001.ts")

    @patch("uploader.upload_with_retry")
    def test_defers_m3u8_until_queue_drains(self, mock_upload, tmp_output_dir):
        """Playlist upload is deferred; segments in the queue are uploaded first."""
        q = queue.Queue()
        mock_s3 = MagicMock()
        worker = UploadWorkerThread(mock_s3, "bucket", "live", q, playlist_defer_secs=0.01)

        ts_path = os.path.join(tmp_output_dir, "seg_00001.ts")
        with open(ts_path, "wb") as f:
            f.write(b"\x00" * 100)

        m3u8_path = os.path.join(tmp_output_dir, "live.m3u8")
        with open(m3u8_path, "w") as f:
            f.write("#EXTM3U\n")

        # Enqueue playlist BEFORE segment — worker should still upload segment first
        q.put(m3u8_path)
        q.put(ts_path)
        q.put(None)

        worker.run()

        calls = [c.args[1] for c in mock_upload.call_args_list]
        assert calls.index(ts_path) < calls.index(m3u8_path)

    @patch("uploader.upload_with_retry")
    def test_stops_on_sentinel(self, mock_upload):
        q = queue.Queue()
        mock_s3 = MagicMock()
        worker = UploadWorkerThread(mock_s3, "bucket", "live", q)

        q.put(None)
        worker.run()

        mock_upload.assert_not_called()

    @patch("uploader.upload_with_retry")
    def test_handles_multiple_segments_before_playlist(self, mock_upload, tmp_output_dir):
        q = queue.Queue()
        mock_s3 = MagicMock()
        worker = UploadWorkerThread(mock_s3, "bucket", "live", q, playlist_defer_secs=0.01)

        paths = []
        for i in range(3):
            ts_path = os.path.join(tmp_output_dir, f"seg_{i:05d}.ts")
            with open(ts_path, "wb") as f:
                f.write(b"\x00" * 100)
            paths.append(ts_path)

        m3u8_path = os.path.join(tmp_output_dir, "live.m3u8")
        with open(m3u8_path, "w") as f:
            f.write("#EXTM3U\n")

        q.put(m3u8_path)
        for p in paths:
            q.put(p)
        q.put(None)

        worker.run()

        upload_paths = [c.args[1] for c in mock_upload.call_args_list]
        # All 3 segments should be uploaded before the playlist
        m3u8_idx = upload_paths.index(m3u8_path)
        for p in paths:
            assert upload_paths.index(p) < m3u8_idx

    @patch("uploader.upload_with_retry")
    def test_flushes_deferred_playlist_on_shutdown(self, mock_upload, tmp_output_dir):
        """When sentinel arrives, any deferred playlist is still uploaded."""
        q = queue.Queue()
        mock_s3 = MagicMock()
        worker = UploadWorkerThread(mock_s3, "bucket", "live", q, playlist_defer_secs=0.01)

        m3u8_path = os.path.join(tmp_output_dir, "live.m3u8")
        with open(m3u8_path, "w") as f:
            f.write("#EXTM3U\n")

        q.put(m3u8_path)
        q.put(None)

        worker.run()

        mock_upload.assert_called_once_with(mock_s3, m3u8_path, "bucket", "live/live.m3u8")
