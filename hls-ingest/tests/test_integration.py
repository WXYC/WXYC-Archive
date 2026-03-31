"""Integration tests: real ffmpeg + mocked S3 via moto.

These tests require ffmpeg to be installed and are marked with
@pytest.mark.integration so they don't run by default.
"""

import os
import time

import boto3
import pytest
from moto import mock_aws

from config import Config
from ingest import IngestProcess, build_ffmpeg_args
from uploader import UploadWorker, upload_with_retry


@pytest.fixture
def moto_s3():
    """Provide a mocked S3 client via moto."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client


@pytest.fixture
def integration_config():
    """Config suitable for integration tests."""
    return Config(
        stream_url="https://audio-mp3.ibiblio.org/wxyc.mp3",
        s3_bucket="test-bucket",
        s3_prefix="live",
        aws_region="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
        hls_segment_duration=2,
        hls_list_size=5,
        health_port=18090,
    )


@pytest.mark.integration
def test_upload_to_mocked_s3(moto_s3, tmp_path):
    """Verify that upload_with_retry sends a file to the mocked S3 bucket."""
    test_file = tmp_path / "seg_00001.ts"
    test_file.write_bytes(b"\x00" * 512)

    result = upload_with_retry(moto_s3, str(test_file), "test-bucket", "live/seg_00001.ts")
    assert result is True

    obj = moto_s3.get_object(Bucket="test-bucket", Key="live/seg_00001.ts")
    assert obj["ContentLength"] == 512
    assert obj["ContentType"] == "video/MP2T"


@pytest.mark.integration
def test_upload_m3u8_content_type(moto_s3, tmp_path):
    """Verify that .m3u8 files get the correct content type in S3."""
    playlist = tmp_path / "live.m3u8"
    playlist.write_text("#EXTM3U\n#EXT-X-VERSION:3\n")

    upload_with_retry(moto_s3, str(playlist), "test-bucket", "live/live.m3u8")

    obj = moto_s3.get_object(Bucket="test-bucket", Key="live/live.m3u8")
    assert obj["ContentType"] == "application/vnd.apple.mpegurl"


@pytest.mark.integration
def test_ffmpeg_args_are_well_formed(integration_config, tmp_path):
    """Verify ffmpeg args form a valid command structure."""
    output_dir = str(tmp_path / "hls")
    os.makedirs(output_dir)
    args = build_ffmpeg_args(integration_config, output_dir)

    assert args[0] == "ffmpeg"
    assert "-i" in args
    assert "-f" in args
    idx = args.index("-f")
    assert args[idx + 1] == "hls"
