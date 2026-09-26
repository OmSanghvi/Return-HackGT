#!/usr/bin/env bash
# Read-only prerequisites for an intentional AWS GPU deployment. This script
# never creates, starts, stops, or modifies an AWS resource.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_DIR="$ROOT/infra/aws"

fail() { echo "ERROR: $*" >&2; exit 1; }
check() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

check aws
check terraform
check curl

aws sts get-caller-identity --output json >/dev/null || fail "AWS CLI authentication failed."
terraform -chdir="$AWS_DIR" version >/dev/null

if [[ ! -f "$AWS_DIR/terraform.tfvars" ]]; then
  fail "Copy infra/aws/terraform.tfvars.example to infra/aws/terraform.tfvars and set a restricted allowed_cidr."
fi

if grep -Eq 'allowed_cidr[[:space:]]*=[[:space:]]*"0\.0\.0\.0/0"' "$AWS_DIR/terraform.tfvars"; then
  fail "allowed_cidr must not expose the API to 0.0.0.0/0."
fi
if grep -Eq '203\.0\.113\.10/32' "$AWS_DIR/terraform.tfvars"; then
  fail "Replace the documentation-only allowed_cidr in terraform.tfvars."
fi

terraform -chdir="$AWS_DIR" fmt -check -recursive
if [[ -d "$AWS_DIR/.terraform" ]]; then
  terraform -chdir="$AWS_DIR" validate
else
  echo "Terraform providers are not initialized; skipping validate. Run terraform init, then rerun this preflight."
fi

echo "Read-only AWS preflight passed. No resources were changed. Review terraform plan before requesting approval to apply."
