#!/usr/bin/env bash
#
# Build, push, and deploy the HLS ingest service to AWS.
#
# Usage:
#   ./deploy.sh <staging|production> [image-tag]
#
# The script reads AWS resource IDs from infra/env.<environment>.conf.
# Copy the .example file and fill in your values before first use.
#
# Prerequisites:
#   - AWS CLI configured (aws sts get-caller-identity works)
#   - Docker installed
#   - env.<environment>.conf filled in
#
# What it does:
#   1. Creates the ECR repository if it doesn't exist
#   2. Builds and pushes the Docker image
#   3. Deploys (or updates) the CloudFormation stack

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
REPO_NAME="wxyc/hls-ingest"
STACK_PREFIX="hls-ingest"

# ── Parse arguments ──────────────────────────────────────────────────────────

ENV="${1:-}"
IMAGE_TAG="${2:-$(git -C "$SERVICE_DIR" rev-parse --short HEAD)}"

if [[ -z "$ENV" ]] || [[ "$ENV" != "staging" && "$ENV" != "production" ]]; then
    echo "Usage: $0 <staging|production> [image-tag]"
    echo ""
    echo "  image-tag defaults to the current git short SHA ($IMAGE_TAG)"
    exit 1
fi

# ── Load environment config ──────────────────────────────────────────────────

CONF_FILE="$SCRIPT_DIR/env.${ENV}.conf"

if [[ ! -f "$CONF_FILE" ]]; then
    echo "Error: $CONF_FILE not found."
    echo ""
    echo "  cp $SCRIPT_DIR/env.${ENV}.conf.example $CONF_FILE"
    echo "  # Fill in your AWS resource IDs, then re-run this script."
    exit 1
fi

# shellcheck source=/dev/null
source "$CONF_FILE"

for var in VPC_ID SUBNET_IDS HOSTED_ZONE_ID CERTIFICATE_ARN; do
    if [[ -z "${!var:-}" ]]; then
        echo "Error: $var is not set in $CONF_FILE"
        exit 1
    fi
done

# ── Resolve AWS account and region ───────────────────────────────────────────

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGION="$(aws configure get region || echo "us-east-1")"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  WXYC HLS Ingest — Deploy                          ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Environment:  $ENV"
echo "║  Image tag:    $IMAGE_TAG"
echo "║  Account:      $ACCOUNT_ID"
echo "║  Region:       $REGION"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── ECR repository ───────────────────────────────────────────────────────────

echo "▶ Checking ECR repository..."
if ! aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$REGION" >/dev/null 2>&1; then
    echo "  Creating ECR repository: $REPO_NAME"
    aws ecr create-repository \
        --repository-name "$REPO_NAME" \
        --region "$REGION" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability MUTABLE >/dev/null
    # Keep only the last 10 images to avoid unbounded storage growth.
    aws ecr put-lifecycle-policy \
        --repository-name "$REPO_NAME" \
        --region "$REGION" \
        --lifecycle-policy-text '{
            "rules": [{
                "rulePriority": 1,
                "description": "Keep last 10 images",
                "selection": {
                    "tagStatus": "any",
                    "countType": "imageCountMoreThan",
                    "countNumber": 10
                },
                "action": { "type": "expire" }
            }]
        }' >/dev/null
    echo "  ✓ Created"
else
    echo "  ✓ Already exists"
fi

# ── Build and push Docker image ──────────────────────────────────────────────

echo ""
echo "▶ Building Docker image..."
docker build -t "$REPO_NAME:$IMAGE_TAG" "$SERVICE_DIR"

echo ""
echo "▶ Pushing to ECR..."
aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "$ECR_URI"
docker tag "$REPO_NAME:$IMAGE_TAG" "$ECR_URI/$REPO_NAME:$IMAGE_TAG"
docker push "$ECR_URI/$REPO_NAME:$IMAGE_TAG"
echo "  ✓ Pushed $ECR_URI/$REPO_NAME:$IMAGE_TAG"

# ── Deploy CloudFormation stack ──────────────────────────────────────────────

STACK_NAME="${STACK_PREFIX}-${ENV}"

echo ""
echo "▶ Deploying CloudFormation stack: $STACK_NAME"
aws cloudformation deploy \
    --template-file "$SCRIPT_DIR/template.yaml" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides \
        "Environment=$ENV" \
        "VpcId=$VPC_ID" \
        "SubnetIds=$SUBNET_IDS" \
        "HostedZoneId=$HOSTED_ZONE_ID" \
        "CertificateArn=$CERTIFICATE_ARN" \
        "ImageTag=$IMAGE_TAG" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset \
    --region "$REGION"

echo ""
echo "▶ Stack outputs:"
aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[*].[OutputKey, OutputValue]" \
    --output table

echo ""
echo "✓ Deploy complete."
