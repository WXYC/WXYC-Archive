# hls-ingest

HLS ingest service that captures the WXYC ibiblio MP3 stream, segments it into HLS via ffmpeg, and uploads segments to S3.

## Architecture

- `main.py` -- Entry point. Orchestrates ffmpeg, S3 uploader, and health endpoint.
- `config.py` -- Loads configuration from environment variables with defaults.
- `ingest.py` -- Manages the ffmpeg subprocess with automatic restart on crash.
- `uploader.py` -- Watches the output directory for new .ts/.m3u8 files and uploads them to S3 with retry.
- `health.py` -- HTTP health endpoint at :8090/health reporting ffmpeg status.

## Infrastructure

- `infra/template.yaml` -- CloudFormation template. Parameterized for staging and production via `Environment` parameter. Creates: S3 bucket, CloudFront distribution (OAC, HTTPS, custom domain), ECS Fargate service, IAM roles, Route 53 DNS record.
- `infra/deploy.sh` -- Builds the Docker image, pushes to ECR, and deploys the CloudFormation stack. Usage: `./infra/deploy.sh <staging|production> [image-tag]`.
- `infra/env.<env>.conf` -- Environment-specific AWS resource IDs (VPC, subnets, hosted zone, ACM cert). Gitignored. Copy from `.example` and fill in your values.
- `scripts/provision-aws.sh` -- Deprecated. Replaced by the CloudFormation template.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
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
| `AWS_ACCESS_KEY_ID` | -- | Local only | AWS credentials. Not needed on ECS Fargate (task role provides credentials automatically). |
| `AWS_SECRET_ACCESS_KEY` | -- | Local only | AWS credentials. Not needed on ECS Fargate (task role provides credentials automatically). |
| `HLS_SEGMENT_DURATION` | `6` | No | Segment length in seconds |
| `HLS_LIST_SIZE` | `600` | No | Max segments in playlist |
| `HEALTH_PORT` | `8090` | No | Health endpoint port |

## Docker

```bash
docker build -t hls-ingest .
docker run -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... hls-ingest
```

## Deployment

Prerequisites: AWS CLI configured, a VPC with public subnets, a Route 53 hosted zone for wxyc.org, and an ACM certificate in us-east-1 covering hls.wxyc.org / hls-staging.wxyc.org.

First deploy:

```bash
cd infra
cp env.staging.conf.example env.staging.conf
# Fill in VPC_ID, SUBNET_IDS, HOSTED_ZONE_ID, CERTIFICATE_ARN
./deploy.sh staging
```

Subsequent deploys (auto-tags with git SHA):

```bash
./infra/deploy.sh staging
```

Check status:

```bash
aws ecs describe-services --cluster hls-ingest-staging --services hls-ingest-staging
aws cloudformation describe-stacks --stack-name hls-ingest-staging
```
