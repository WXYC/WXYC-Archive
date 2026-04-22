"""Entry point for the HLS ingest service.

Orchestrates ffmpeg ingest, S3 upload, and health endpoint.
"""

import asyncio
import logging
import shutil
import signal
import sys
import tempfile
import threading

import boto3

from config import Config
from health import run_health_server
from ingest import IngestProcess
from uploader import UploadWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the HLS ingest service."""
    try:
        config = Config.from_env()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    output_dir = tempfile.mkdtemp(prefix="hls-ingest-")
    logger.info("HLS output directory: %s", output_dir)

    # Set up S3 client. When credentials are provided (local dev), pass them
    # explicitly. When omitted (ECS Fargate), boto3 discovers them from the
    # task role automatically.
    s3_kwargs = {"region_name": config.aws_region}
    if config.aws_access_key_id and config.aws_secret_access_key:
        s3_kwargs["aws_access_key_id"] = config.aws_access_key_id
        s3_kwargs["aws_secret_access_key"] = config.aws_secret_access_key
    s3_client = boto3.client("s3", **s3_kwargs)

    # Set up components
    ingest = IngestProcess(config, output_dir)
    uploader = UploadWorker(s3_client, config.s3_bucket, config.s3_prefix, output_dir)

    # Graceful shutdown handler
    def handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        ingest.stop()
        uploader.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Start upload worker
    uploader.start()

    # Start health endpoint in async thread
    loop = asyncio.new_event_loop()

    async def start_health():
        return await run_health_server(config.health_port, ingest.is_alive)

    health_runner = None

    def run_health_loop():
        nonlocal health_runner
        asyncio.set_event_loop(loop)
        health_runner = loop.run_until_complete(start_health())
        loop.run_forever()

    health_thread = threading.Thread(target=run_health_loop, daemon=True)
    health_thread.start()

    # Run ffmpeg ingest (blocks until stopped)
    try:
        ingest.run_forever()
    finally:
        uploader.stop()
        loop.call_soon_threadsafe(loop.stop)
        shutil.rmtree(output_dir, ignore_errors=True)
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
