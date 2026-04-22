"""Environment variable configuration for the HLS ingest service."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable configuration loaded from environment variables."""

    stream_url: str
    s3_bucket: str
    s3_prefix: str
    aws_region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    hls_segment_duration: int
    hls_list_size: int
    health_port: int

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables.

        Optional (with defaults).

        AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are optional. When omitted,
        boto3 discovers credentials from the environment (e.g., IAM task role
        on ECS Fargate). Set them explicitly for local development.

        Other optional variables:
            IBIBLIO_STREAM_URL: Source MP3 stream URL (default: https://audio-mp3.ibiblio.org/wxyc.mp3).
            S3_BUCKET: Target S3 bucket name (default: wxyc-hls).
            S3_PREFIX: Key prefix for uploaded objects (default: live).
            AWS_REGION: AWS region (default: us-east-1).
            HLS_SEGMENT_DURATION: Segment duration in seconds (default: 6).
            HLS_LIST_SIZE: Maximum number of segments in the playlist (default: 600).
            HEALTH_PORT: Port for the health HTTP endpoint (default: 8090).
        """
        raw_segment_duration = os.environ.get("HLS_SEGMENT_DURATION", "6")
        raw_list_size = os.environ.get("HLS_LIST_SIZE", "600")
        raw_health_port = os.environ.get("HEALTH_PORT", "8090")

        segment_duration = _parse_positive_int(raw_segment_duration, "HLS_SEGMENT_DURATION")
        list_size = _parse_positive_int(raw_list_size, "HLS_LIST_SIZE")
        health_port = _parse_positive_int(raw_health_port, "HEALTH_PORT")

        aws_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
        aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

        return cls(
            stream_url=os.environ.get(
                "IBIBLIO_STREAM_URL", "https://audio-mp3.ibiblio.org/wxyc.mp3"
            ),
            s3_bucket=os.environ.get("S3_BUCKET", "wxyc-hls"),
            s3_prefix=os.environ.get("S3_PREFIX", "live"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            hls_segment_duration=segment_duration,
            hls_list_size=list_size,
            health_port=health_port,
        )


def _parse_positive_int(value: str, name: str) -> int:
    """Parse a string as a positive integer, raising ValueError on failure."""
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value!r}")
    if parsed <= 0:
        raise ValueError(f"{name} must be positive, got: {parsed}")
    return parsed
