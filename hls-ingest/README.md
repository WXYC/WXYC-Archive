# hls-ingest

HLS ingest service for WXYC 89.3 FM. Captures the ibiblio MP3 stream, transcodes it into HLS (AAC) segments via ffmpeg, and continuously uploads them to S3 for browser-based time-shifted playback.

## How It Works

1. **ffmpeg** connects to the WXYC ibiblio MP3 stream and produces AAC-encoded HLS segments (6 seconds each by default) with a sliding window playlist.
2. A **watchdog** file observer detects new `.ts` segments and `.m3u8` playlist updates in the output directory.
3. The **S3 uploader** pushes each file to the configured bucket with the correct `Content-Type` headers, retrying with exponential backoff on failure.
4. If ffmpeg crashes or the stream disconnects, the process supervisor automatically restarts it after a brief cooldown.
5. A **/health** HTTP endpoint on port 8090 reports whether ffmpeg is alive, suitable for container health checks.

## Quick Start

```bash
# Set up
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests
pytest

# Run the service (requires AWS credentials)
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
python main.py
```

## Docker

```bash
docker build -t hls-ingest .
docker run \
  -e AWS_ACCESS_KEY_ID=... \
  -e AWS_SECRET_ACCESS_KEY=... \
  -p 8090:8090 \
  hls-ingest
```

## AWS Provisioning

The `scripts/provision-aws.sh` script creates the S3 bucket with lifecycle rules, CORS, and a public read policy:

```bash
./scripts/provision-aws.sh [bucket-name] [region]
```

## Configuration

All configuration is via environment variables. See `CLAUDE.md` for the full table.

## Testing

Unit tests run by default. Integration tests (requiring ffmpeg and using moto for S3) are marked with `@pytest.mark.integration`:

```bash
pytest                    # unit tests
pytest -m integration     # integration tests
```
