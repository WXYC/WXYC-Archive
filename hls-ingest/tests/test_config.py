"""Tests for environment variable configuration parsing."""

import pytest

from config import Config, _parse_positive_int


class TestParsePositiveInt:
    """Tests for the _parse_positive_int helper."""

    def test_valid_integer(self):
        assert _parse_positive_int("42", "TEST") == 42

    def test_one_is_valid(self):
        assert _parse_positive_int("1", "TEST") == 1

    @pytest.mark.parametrize("value", ["0", "-1", "-100"])
    def test_non_positive_raises(self, value):
        with pytest.raises(ValueError, match="must be positive"):
            _parse_positive_int(value, "TEST")

    @pytest.mark.parametrize("value", ["abc", "3.14", "", " "])
    def test_non_integer_raises(self, value):
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_positive_int(value, "TEST")


class TestConfigFromEnv:
    """Tests for Config.from_env()."""

    def test_defaults_with_required_keys(self, env_with_aws):
        config = Config.from_env()
        assert config.stream_url == "https://audio-mp3.ibiblio.org/wxyc.mp3"
        assert config.s3_bucket == "wxyc-hls"
        assert config.s3_prefix == "live"
        assert config.aws_region == "us-east-1"
        assert config.hls_segment_duration == 6
        assert config.hls_list_size == 600
        assert config.health_port == 8090

    def test_no_aws_credentials_defaults_to_empty(self, monkeypatch):
        """Credentials are optional; boto3 discovers them from IAM roles on Fargate."""
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        config = Config.from_env()
        assert config.aws_access_key_id == ""
        assert config.aws_secret_access_key == ""

    def test_partial_credentials_still_succeeds(self, monkeypatch):
        """Credential validation is deferred to boto3 at runtime, not config loading."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        config = Config.from_env()
        assert config.aws_access_key_id == "AKIAIOSFODNN7EXAMPLE"
        assert config.aws_secret_access_key == ""

    def test_custom_env_values(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        monkeypatch.setenv("IBIBLIO_STREAM_URL", "http://localhost:8000/stream.mp3")
        monkeypatch.setenv("S3_BUCKET", "my-bucket")
        monkeypatch.setenv("S3_PREFIX", "staging")
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("HLS_SEGMENT_DURATION", "10")
        monkeypatch.setenv("HLS_LIST_SIZE", "300")
        monkeypatch.setenv("HEALTH_PORT", "9090")

        config = Config.from_env()
        assert config.stream_url == "http://localhost:8000/stream.mp3"
        assert config.s3_bucket == "my-bucket"
        assert config.s3_prefix == "staging"
        assert config.aws_region == "eu-west-1"
        assert config.hls_segment_duration == 10
        assert config.hls_list_size == 300
        assert config.health_port == 9090

    def test_invalid_segment_duration_raises(self, env_with_aws, monkeypatch):
        monkeypatch.setenv("HLS_SEGMENT_DURATION", "not-a-number")
        with pytest.raises(ValueError, match="HLS_SEGMENT_DURATION"):
            Config.from_env()

    def test_zero_list_size_raises(self, env_with_aws, monkeypatch):
        monkeypatch.setenv("HLS_LIST_SIZE", "0")
        with pytest.raises(ValueError, match="HLS_LIST_SIZE"):
            Config.from_env()

    def test_config_is_immutable(self, sample_config):
        with pytest.raises(AttributeError):
            sample_config.s3_bucket = "other-bucket"
