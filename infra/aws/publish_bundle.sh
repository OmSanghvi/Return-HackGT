#!/usr/bin/env bash
# Copy this workspace privately to the already-created EC2 host. It does not
# bootstrap models or start a GPU job; those need a locally entered HF token.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$SCRIPT_DIR"
REGION="${AWS_REGION:-$(terraform -chdir="$TF_DIR" output -raw aws_region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"
BUCKET="$(terraform -chdir="$TF_DIR" output -raw bundle_bucket)"
INSTANCE_ID="$(terraform -chdir="$TF_DIR" output -raw instance_id)"
STAGE_DIR="$(mktemp -d)"
ARCHIVE="$STAGE_DIR/sketchscape.tgz"
trap 'rm -rf "$STAGE_DIR"' EXIT

tar -C "$PROJECT_DIR" -czf "$ARCHIVE" \
  --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='.DS_Store' \
  --exclude='data' --exclude='token.txt' --exclude='infra/aws/terraform.tfvars' \
  --exclude='infra/aws/.terraform' --exclude='infra/aws/terraform.tfstate*' \
  --exclude='infra/aws/tfplan' --exclude='.sam3d-fast-checkpoints' \
  --exclude='sam3d_hf_zerogpu_space/.cache' .
aws s3 cp "$ARCHIVE" "s3://$BUCKET/releases/sketchscape.tgz" --sse AES256 --region "$REGION"
COMMAND_ID="$(aws ssm send-command \
  --region "$REGION" \
  --document-name AWS-RunShellScript \
  --instance-ids "$INSTANCE_ID" \
  --parameters commands='sudo apt-get update -y; sudo apt-get install -y awscli; sudo mkdir -p /opt/sketchscape; sudo aws s3 cp s3://'"$BUCKET"'/releases/sketchscape.tgz /tmp/sketchscape.tgz; sudo tar -xzf /tmp/sketchscape.tgz -C /opt/sketchscape; sudo chown -R ubuntu:ubuntu /opt/sketchscape' \
  --query 'Command.CommandId' --output text)"
echo "Uploaded workspace. Wait for SSM command: $COMMAND_ID"
echo "aws ssm get-command-invocation --region $REGION --command-id $COMMAND_ID --instance-id $INSTANCE_ID"
