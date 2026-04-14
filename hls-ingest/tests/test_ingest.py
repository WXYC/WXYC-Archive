"""Tests for ffmpeg process lifecycle: start, crash-restart, reconnect."""

import os
import subprocess
from unittest.mock import MagicMock, patch


from ingest import IngestProcess, build_ffmpeg_args


class TestBuildFfmpegArgs:
    """Tests for the ffmpeg argument builder."""

    def test_contains_input_url(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        assert sample_config.stream_url in args

    def test_contains_aac_codec(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        idx = args.index("-c:a")
        assert args[idx + 1] == "aac"

    def test_contains_hls_time(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        idx = args.index("-hls_time")
        assert args[idx + 1] == "6"

    def test_contains_hls_list_size(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        idx = args.index("-hls_list_size")
        assert args[idx + 1] == "600"

    def test_output_path_is_in_output_dir(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        playlist_path = args[-1]
        assert playlist_path == os.path.join(tmp_output_dir, "live.m3u8")

    def test_segment_pattern_is_in_output_dir(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        idx = args.index("-hls_segment_filename")
        segment_pattern = args[idx + 1]
        assert segment_pattern.startswith(tmp_output_dir)
        assert "seg_" in segment_pattern

    def test_reconnect_flags_present(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        assert "-reconnect" in args
        assert "-reconnect_streamed" in args

    def test_hls_flags_include_delete_segments(self, sample_config, tmp_output_dir):
        args = build_ffmpeg_args(sample_config, tmp_output_dir)
        idx = args.index("-hls_flags")
        assert "delete_segments" in args[idx + 1]


class TestIngestProcess:
    """Tests for the IngestProcess class."""

    @patch("ingest.subprocess.Popen")
    def test_start_launches_ffmpeg(self, mock_popen, sample_config, tmp_output_dir):
        proc = IngestProcess(sample_config, tmp_output_dir)
        mock_popen.return_value = MagicMock()
        proc.start()
        mock_popen.assert_called_once()
        assert proc.process is not None

    @patch("ingest.subprocess.Popen")
    def test_stop_terminates_process(self, mock_popen, sample_config, tmp_output_dir):
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        proc = IngestProcess(sample_config, tmp_output_dir)
        proc.start()
        proc.stop()

        mock_process.terminate.assert_called_once()
        assert proc.running is False
        assert proc.process is None

    @patch("ingest.subprocess.Popen")
    def test_stop_kills_if_terminate_times_out(self, mock_popen, sample_config, tmp_output_dir):
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("ffmpeg", 10), None]
        mock_popen.return_value = mock_process

        proc = IngestProcess(sample_config, tmp_output_dir)
        proc.start()
        proc.stop()

        mock_process.kill.assert_called_once()

    @patch("ingest.subprocess.Popen")
    def test_is_alive_when_running(self, mock_popen, sample_config, tmp_output_dir):
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        proc = IngestProcess(sample_config, tmp_output_dir)
        proc.start()
        assert proc.is_alive() is True

    @patch("ingest.subprocess.Popen")
    def test_is_alive_false_when_exited(self, mock_popen, sample_config, tmp_output_dir):
        mock_process = MagicMock()
        mock_process.poll.return_value = 1
        mock_popen.return_value = mock_process

        proc = IngestProcess(sample_config, tmp_output_dir)
        proc.start()
        assert proc.is_alive() is False

    def test_is_alive_false_before_start(self, sample_config, tmp_output_dir):
        proc = IngestProcess(sample_config, tmp_output_dir)
        assert proc.is_alive() is False

    @patch("ingest.subprocess.Popen")
    @patch("ingest.time.sleep")
    def test_run_forever_restarts_on_crash(
        self, mock_sleep, mock_popen, sample_config, tmp_output_dir
    ):
        """Verify that run_forever restarts ffmpeg after a crash."""
        call_count = 0

        def create_mock_process(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            # On first call, simulate immediate exit. On second call, stop the loop.
            if call_count >= 2:
                # Stop the loop after second launch
                proc.running = False
            return mock_proc

        mock_popen.side_effect = create_mock_process

        proc = IngestProcess(sample_config, tmp_output_dir)
        proc.run_forever()

        assert call_count == 2
        assert mock_popen.call_count == 2


class TestStderrDraining:
    """Tests for stderr pipe draining to prevent subprocess deadlock."""

    @patch("ingest.subprocess.Popen")
    def test_start_launches_stderr_drain_thread(self, mock_popen, sample_config, tmp_output_dir):
        """Verify that starting ffmpeg also starts a daemon thread to drain stderr."""
        mock_process = MagicMock()
        mock_process.stderr = MagicMock()
        mock_popen.return_value = mock_process

        proc = IngestProcess(sample_config, tmp_output_dir)

        with patch("ingest.threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            proc.start()

            mock_thread_cls.assert_called_once()
            assert mock_thread_cls.call_args.kwargs.get("daemon") is True
            mock_thread.start.assert_called_once()

    def test_drain_stderr_logs_lines(self, sample_config, tmp_output_dir):
        """Verify that _drain_stderr reads and logs each line from the pipe."""
        import io

        proc = IngestProcess(sample_config, tmp_output_dir)
        fake_stderr = io.BytesIO(b"frame=100 fps=25\nsize=1024kB time=00:00:04\n")

        with patch("ingest.logger") as mock_logger:
            proc._drain_stderr(fake_stderr)
            assert mock_logger.debug.call_count == 2

    def test_drain_stderr_handles_empty_stream(self, sample_config, tmp_output_dir):
        """Verify _drain_stderr handles EOF gracefully."""
        import io

        proc = IngestProcess(sample_config, tmp_output_dir)
        fake_stderr = io.BytesIO(b"")

        # Should not raise
        proc._drain_stderr(fake_stderr)
