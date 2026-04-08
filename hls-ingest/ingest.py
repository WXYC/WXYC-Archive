"""ffmpeg subprocess management for HLS segmentation of the WXYC ibiblio stream."""

import logging
import os
import subprocess
import time

from config import Config

logger = logging.getLogger(__name__)

# Minimum seconds between restart attempts to avoid tight restart loops.
MIN_RESTART_INTERVAL = 5.0


def build_ffmpeg_args(config: Config, output_dir: str) -> list[str]:
    """Build the ffmpeg command-line arguments for HLS segmentation.

    Connects to the ibiblio MP3 stream and outputs AAC-encoded HLS segments
    with the configured segment duration and playlist window size.

    Args:
        config: Service configuration.
        output_dir: Directory where .ts segments and .m3u8 playlist are written.

    Returns:
        List of command-line arguments suitable for subprocess.Popen.
    """
    playlist_path = os.path.join(output_dir, "live.m3u8")
    segment_pattern = os.path.join(output_dir, "seg_%05d.ts")

    return [
        "ffmpeg",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "30",
        "-i",
        config.stream_url,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-f",
        "hls",
        "-hls_time",
        str(config.hls_segment_duration),
        "-hls_list_size",
        str(config.hls_list_size),
        "-hls_flags",
        "delete_segments+append_list",
        "-hls_segment_filename",
        segment_pattern,
        playlist_path,
    ]


class IngestProcess:
    """Manages the ffmpeg subprocess lifecycle with automatic restart on failure.

    Attributes:
        config: Service configuration.
        output_dir: Directory for HLS output files.
        process: The currently running ffmpeg subprocess, or None.
        running: Whether the ingest loop should continue.
    """

    def __init__(self, config: Config, output_dir: str) -> None:
        self.config = config
        self.output_dir = output_dir
        self.process: subprocess.Popen | None = None
        self.running: bool = False
        self._last_start_time: float = 0.0

    def start(self) -> None:
        """Launch the ffmpeg process."""
        os.makedirs(self.output_dir, exist_ok=True)
        args = build_ffmpeg_args(self.config, self.output_dir)
        logger.info("Starting ffmpeg: %s", " ".join(args))
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._last_start_time = time.monotonic()

    def stop(self) -> None:
        """Gracefully stop the ffmpeg process."""
        self.running = False
        if self.process and self.process.poll() is None:
            logger.info("Stopping ffmpeg (pid %d)", self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("ffmpeg did not exit in time, killing")
                self.process.kill()
                self.process.wait()
        self.process = None

    def is_alive(self) -> bool:
        """Check whether the ffmpeg process is currently running."""
        return self.process is not None and self.process.poll() is None

    def run_forever(self) -> None:
        """Run the ffmpeg process in a loop, restarting on crash.

        Blocks until stop() is called from another thread. Enforces a minimum
        restart interval to avoid tight loops when ffmpeg fails immediately.
        """
        self.running = True
        while self.running:
            self.start()
            if self.process is None:
                break

            self.process.wait()
            exit_code = self.process.returncode
            logger.warning("ffmpeg exited with code %d", exit_code)

            if not self.running:
                break

            # Enforce minimum restart interval
            elapsed = time.monotonic() - self._last_start_time
            if elapsed < MIN_RESTART_INTERVAL:
                delay = MIN_RESTART_INTERVAL - elapsed
                logger.info("Waiting %.1fs before restart", delay)
                time.sleep(delay)

            logger.info("Restarting ffmpeg...")
