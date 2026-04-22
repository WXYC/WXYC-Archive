#!/usr/bin/env bash
#
# DEPRECATED: This script is superseded by the CloudFormation template at
# infra/template.yaml. Use infra/deploy.sh to provision and deploy.
# This file is retained for reference during migration.
#
# Provision AWS resources for the HLS ingest service.
#
# Creates the S3 bucket with a lifecycle rule to expire old segments,
# and configures CORS for browser-based HLS playback.
#
# Usage:
#   ./scripts/provision-aws.sh [bucket-name] [region]
#
# Defaults:
#   bucket-name: wxyc-hls
#   region: us-east-1

set -euo pipefail

BUCKET="${1:-wxyc-hls}"
REGION="${2:-us-east-1}"

echo "Provisioning S3 bucket: $BUCKET in $REGION"

# Create bucket
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    echo "Bucket $BUCKET already exists"
else
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
    else
        aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION"
    fi
    echo "Created bucket $BUCKET"
fi

# Enable versioning (protects against accidental overwrites of the playlist)
aws s3api put-bucket-versioning --bucket "$BUCKET" \
    --versioning-configuration Status=Enabled
echo "Enabled versioning"

# Lifecycle rule: expire segments older than 2 days.
# The sliding window is maintained by ffmpeg's delete_segments flag, but this
# acts as a safety net for any segments that slip through.
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
    --lifecycle-configuration '{
        "Rules": [
            {
                "ID": "expire-old-segments",
                "Status": "Enabled",
                "Filter": {
                    "Prefix": "live/"
                },
                "Expiration": {
                    "Days": 2
                }
            },
            {
                "ID": "expire-old-versions",
                "Status": "Enabled",
                "Filter": {
                    "Prefix": "live/"
                },
                "NoncurrentVersionExpiration": {
                    "NoncurrentDays": 1
                }
            }
        ]
    }'
echo "Configured lifecycle rules (expire segments after 2 days, old versions after 1 day)"

# CORS configuration for browser-based HLS playback
aws s3api put-bucket-cors --bucket "$BUCKET" \
    --cors-configuration '{
        "CORSRules": [
            {
                "AllowedOrigins": ["*"],
                "AllowedMethods": ["GET", "HEAD"],
                "AllowedHeaders": ["*"],
                "MaxAgeSeconds": 3600
            }
        ]
    }'
echo "Configured CORS for HLS playback"

# NOTE: Do not grant public read access directly on the bucket. Instead,
# configure a CloudFront Origin Access Control (OAC) to restrict S3 access
# to CloudFront only. The OAC should be created as part of the CloudFront
# distribution setup, which is outside the scope of this provisioning script.
#
# See: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html

echo ""
echo "Provisioning complete."
echo "Configure a CloudFront distribution with OAC to serve:"
echo "  https://<distribution>.cloudfront.net/live/live.m3u8"
