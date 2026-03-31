#!/usr/bin/env bash
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
            }
        ]
    }'
echo "Configured lifecycle rule (expire after 2 days)"

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

# Bucket policy: allow public read for the live/ prefix
aws s3api put-bucket-policy --bucket "$BUCKET" \
    --policy "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [
            {
                \"Sid\": \"PublicReadHLS\",
                \"Effect\": \"Allow\",
                \"Principal\": \"*\",
                \"Action\": \"s3:GetObject\",
                \"Resource\": \"arn:aws:s3:::$BUCKET/live/*\"
            }
        ]
    }"
echo "Configured public read policy for live/ prefix"

echo ""
echo "Provisioning complete. Stream URL will be:"
echo "  https://$BUCKET.s3.$REGION.amazonaws.com/live/live.m3u8"
