# hls-ingest

HLS ingest service that captures the WXYC ibiblio MP3 stream, segments it into HLS via ffmpeg, and uploads segments to S3.

## Architecture

- `main.py` -- Entry point. Orchestrates ffmpeg, S3 uploader, and health endpoint.
- `config.py` -- Loads configuration from environment variables with defaults.
- `ingest.py` -- Manages the ffmpeg subprocess with automatic restart on crash.
- `uploader.py` -- Watches the output directory for new .ts/.m3u8 files and uploads them to S3 with retry.
- `health.py` -- HTTP health endpoint at :8090/health reporting ffmpeg status.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest                           # unit tests only
pytest -m integration            # integration tests (requires ffmpeg)
```

## Testing

- Unit tests run by default (`pytest`). They use mocks for ffmpeg and S3.
- Integration tests are marked with `@pytest.mark.integration` and require ffmpeg installed locally. They use moto for S3.
- Code style: black + ruff, 100 char line length.

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `IBIBLIO_STREAM_URL` | `https://audio-mp3.ibiblio.org/wxyc.mp3` | No | Source MP3 stream |
| `S3_BUCKET` | `wxyc-hls` | No | Target S3 bucket |
| `S3_PREFIX` | `live` | No | S3 key prefix |
| `AWS_REGION` | `us-east-1` | No | AWS region |
| `AWS_ACCESS_KEY_ID` | -- | Yes | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | -- | Yes | AWS credentials |
| `HLS_SEGMENT_DURATION` | `6` | No | Segment length in seconds |
| `HLS_LIST_SIZE` | `600` | No | Max segments in playlist |
| `HEALTH_PORT` | `8090` | No | Health endpoint port |

## Docker

```bash
docker build -t hls-ingest .
docker run -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... hls-ingest
```
