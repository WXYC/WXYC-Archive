"""Tests for the main module orchestration."""

import os
import tempfile
from unittest.mock import MagicMock, patch


class TestMainCleanup:
    """Tests for resource cleanup in main()."""

    @patch("main.threading.Thread")
    @patch("main.asyncio.new_event_loop")
    @patch("main.signal.signal")
    @patch("main.boto3.client")
    @patch("main.UploadWorker")
    @patch("main.IngestProcess")
    @patch("main.Config.from_env")
    def test_output_dir_cleaned_up_on_normal_exit(
        self,
        mock_from_env,
        mock_ingest_cls,
        mock_uploader_cls,
        mock_boto3_client,
        mock_signal,
        mock_loop,
        mock_thread,
    ):
        """Verify the temp output directory is removed when main() exits."""
        mock_config = MagicMock()
        mock_config.health_port = 8090
        mock_from_env.return_value = mock_config

        mock_ingest = MagicMock()
        mock_ingest.run_forever.return_value = None
        mock_ingest_cls.return_value = mock_ingest

        mock_uploader_cls.return_value = MagicMock()
        mock_thread.return_value = MagicMock()

        captured_dir = {}
        original_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            captured_dir["path"] = d
            return d

        with patch("main.tempfile.mkdtemp", side_effect=tracking_mkdtemp):
            from main import main

            main()

        assert "path" in captured_dir
        assert not os.path.exists(
            captured_dir["path"]
        ), f"Temp directory {captured_dir['path']} should have been cleaned up"
