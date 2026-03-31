"""Tests for S3 uploads: segment detection, retry logic, content types."""

import os
import time
from unittest.mock import MagicMock, call, patch

import pytest

from uploader import (
    HLSUploadHandler,
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
            mock_client, "/tmp/seg.ts", "bucket", "live/seg.ts", max_retries=3, base_backoff=1.0
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


class TestHLSUploadHandler:
    """Tests for the watchdog event handler."""

    def test_handles_ts_file_creation(self, tmp_output_dir):
        mock_client = MagicMock()
        handler = HLSUploadHandler(mock_client, "bucket", "live")

        ts_path = os.path.join(tmp_output_dir, "seg_00001.ts")
        with open(ts_path, "wb") as f:
            f.write(b"\x00" * 100)

        from watchdog.events import FileCreatedEvent

        event = FileCreatedEvent(ts_path)
        with patch("uploader.upload_with_retry") as mock_upload:
            handler.on_created(event)
            mock_upload.assert_called_once_with(
                mock_client, ts_path, "bucket", "live/seg_00001.ts"
            )

    def test_ignores_non_hls_files(self, tmp_output_dir):
        mock_client = MagicMock()
        handler = HLSUploadHandler(mock_client, "bucket", "live")

        txt_path = os.path.join(tmp_output_dir, "notes.txt")
        with open(txt_path, "w") as f:
            f.write("hello")

        from watchdog.events import FileCreatedEvent

        event = FileCreatedEvent(txt_path)
        with patch("uploader.upload_with_retry") as mock_upload:
            handler.on_created(event)
            mock_upload.assert_not_called()

    def test_handles_m3u8_modification(self, tmp_output_dir):
        mock_client = MagicMock()
        handler = HLSUploadHandler(mock_client, "bucket", "live")

        m3u8_path = os.path.join(tmp_output_dir, "live.m3u8")
        with open(m3u8_path, "w") as f:
            f.write("#EXTM3U\n")

        from watchdog.events import FileModifiedEvent

        event = FileModifiedEvent(m3u8_path)
        with patch("uploader.upload_with_retry") as mock_upload:
            handler.on_modified(event)
            mock_upload.assert_called_once()
