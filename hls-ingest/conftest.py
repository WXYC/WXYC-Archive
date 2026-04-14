"""Shared pytest fixtures for the HLS ingest service tests."""

import os

import pytest

from config import Config


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provide a temporary directory for HLS output files."""
    output = tmp_path / "hls-output"
    output.mkdir()
    return str(output)


@pytest.fixture
def sample_config():
    """Provide a Config instance with test defaults."""
    return Config(
        stream_url="https://audio-mp3.ibiblio.org/wxyc.mp3",
        s3_bucket="test-bucket",
        s3_prefix="live",
        aws_region="us-east-1",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        hls_segment_duration=6,
        hls_list_size=600,
        health_port=8090,
    )


@pytest.fixture
def sample_ts_file(tmp_output_dir):
    """Create a sample .ts segment file in the output directory."""
    path = os.path.join(tmp_output_dir, "seg_00001.ts")
    with open(path, "wb") as f:
        f.write(b"\x00" * 1024)
    return path


@pytest.fixture
def sample_m3u8_file(tmp_output_dir):
    """Create a sample .m3u8 playlist file in the output directory."""
    path = os.path.join(tmp_output_dir, "live.m3u8")
    with open(path, "w") as f:
        f.write("#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:6.0,\nseg_00001.ts\n")
    return path


@pytest.fixture
def env_with_aws(monkeypatch):
    """Set minimal required environment variables for Config.from_env()."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
