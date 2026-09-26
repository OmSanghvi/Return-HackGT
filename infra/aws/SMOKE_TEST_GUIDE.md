# AWS storage smoke test guide

This guide walks through provisioning the DynamoDB authoring table and S3
artifacts bucket, then running the live verification script
(`scripts/smoke_test_aws_storage.py`) that confirms both backends work
exactly as the application expects. Every step is explicit and reversible.

## Prerequisites

All of these must be true before you start:

- `aws sts get-caller-identity` succeeds (credentials in the environment or
  `~/.aws`).
- Terraform is installed (`terraform -version` ≥ 1.6).
- You are in the project root: `cd /Users/shruti/HackGT`.
- The current public IP of your machine is already in `terraform.tfvars`
  (`allowed_cidr`). If your IP has changed since the last apply, update it
  first:

  ```bash
  curl -s https://checkip.amazonaws.com
  # update allowed_cidr in infra/aws/terraform.tfvars
  ```

## Cost profile

| Resource | Billing model | Estimated cost at hackathon scale |
|---|---|---|
| DynamoDB table | PAY_PER_REQUEST | < $0.01 for smoke test; ~$0/month at < 1 million requests |
| S3 artifacts bucket | per GB stored + requests | < $0.01 for a few PLY files |
| EIP (already exists) | $0.005/hr while instance is stopped | no change |

The DynamoDB and S3 resources have no hourly component — you only pay for
what you read/write and what you store. The smoke test creates and deletes
all its items, so net storage cost is effectively zero.

## Step 1 — Review the Terraform plan

`terraform.tfvars` already has `enable_dynamodb = true` and
`enable_artifacts_bucket = true`. Inspect what will be created before
applying anything:

```bash
cd infra/aws
terraform plan
```

Expected new resources (8 total):

```
+ aws_dynamodb_resource_policy.authoring_deny_delete[0]
+ aws_dynamodb_table.authoring[0]
+ aws_iam_role_policy.artifacts_bucket[0]
+ aws_iam_role_policy.dynamodb_authoring[0]
+ aws_s3_bucket.artifacts[0]
+ aws_s3_bucket_lifecycle_configuration.artifacts[0]
+ aws_s3_bucket_public_access_block.artifacts[0]
+ aws_s3_bucket_server_side_encryption_configuration.artifacts[0]
+ aws_s3_bucket_versioning.artifacts[0]
```

No existing resources should be modified or destroyed. If you see any
`~` (modify) or `-` (destroy) lines on the instance, EIP, or bundle bucket,
**stop and do not apply** — something has changed in the configuration.

## Step 2 — Apply

Only run this after reviewing the plan output above:

```bash
terraform apply
```

Type `yes` at the prompt. The apply takes about 30 seconds. Terraform will
print the new outputs when done:

```
dynamodb_table_name  = "sketchscape-authoring"
dynamodb_table_arn   = "arn:aws:dynamodb:us-east-2:...:table/sketchscape-authoring"
artifacts_bucket     = "sketchscape-artifacts-<random>"
artifacts_bucket_arn = "arn:aws:s3:::sketchscape-artifacts-<random>"
```

Capture them:

```bash
TABLE=$(terraform output -raw dynamodb_table_name)
BUCKET=$(terraform output -raw artifacts_bucket)
REGION=$(terraform output -raw aws_region)
echo "Table:  $TABLE"
echo "Bucket: $BUCKET"
echo "Region: $REGION"
```

## Step 3 — Install boto3 locally

The smoke test imports boto3 directly. Install it in the backend venv:

```bash
cd ../backend   # from infra/aws
.venv/bin/pip install "boto3>=1.34,<2.0"
```

> boto3 stays out of the base `requirements.txt` by design — it is only
> needed when `SKETCHSCAPE_STORAGE_BACKEND=dynamodb` or
> `SKETCHSCAPE_ARTIFACTS_BACKEND=s3` is selected. It is already listed in
> `requirements-dev.txt` for developer environments.

## Step 4 — Run the smoke test

From the project root:

```bash
cd /Users/shruti/HackGT
SKETCHSCAPE_DYNAMODB_TABLE="$TABLE" \
SKETCHSCAPE_ARTIFACTS_BUCKET="$BUCKET" \
AWS_REGION="$REGION" \
backend/.venv/bin/python scripts/smoke_test_aws_storage.py
```

### What the script checks

**DynamoDB section:**

| Check | What it verifies |
|---|---|
| save_project / get_project roundtrip | PutItem + GetItem on `PROJECT#…/META` |
| project name survives roundtrip | JSON serialisation round-trips cleanly |
| save_asset / get_asset roundtrip | PutItem + GetItem on `ASSET#…/META` |
| two blueprints stored | append_blueprint writes ordered `BLUEPRINT#` sort keys |
| blueprints returned in creation order | Query with ScanIndexForward returns revisions [1, 2] |
| three publication records stored | append_publication writes ordered `PUBLICATION#` sort keys |
| publication log is append-only [1,2,1] | republishing rev 1 appends a third record, not overwrite |
| project update persists asset_ids | second save_project overwrites the existing META item |

**S3 section:**

| Check | What it verifies |
|---|---|
| put PLY returns canonical URL | upload_file to `artifacts/<job_id>/reconstruction.ply` |
| PLY exists in bucket | head_object succeeds after put |
| mask exists in bucket | second put to `mask.png` |
| serve returns 302 redirect | generate_presigned_url produces a redirect response |
| presigned URL points to correct bucket | bucket name in Location header |
| presigned URL contains expected key path | `artifacts/<job_id>` in Location header |
| copy_local returns canonical URL | upload_file from a local path |
| preview exists in bucket | head_object after copy_local |
| oversize upload rejected with 413 | size check happens before any S3 call |

### Expected output

```
SketchScape AWS storage smoke test
  Region:  us-east-2
  Table:   sketchscape-authoring
  Bucket:  sketchscape-artifacts-<random>
  Run ID:  smoke-<hex>

────────────────────────────────────────────────────────────
  DynamoDB — table: sketchscape-authoring
────────────────────────────────────────────────────────────
  ✓  save_project / get_project roundtrip
  ✓  project name survives roundtrip
  ✓  save_asset / get_asset roundtrip
  ✓  asset label survives
  ✓  two blueprints stored
  ✓  blueprints returned in creation order
  ✓  three publication records stored
  ✓  publication log is append-only [1,2,1]
  ✓  project update persists asset_ids

────────────────────────────────────────────────────────────
  S3 artifacts — bucket: sketchscape-artifacts-<random>
────────────────────────────────────────────────────────────
  ✓  put PLY returns canonical URL
  ✓  PLY exists in bucket
  ✓  mask exists in bucket
  ✓  serve returns 302 redirect
  ✓  presigned URL points to correct bucket
  ✓  presigned URL contains expected key path
  ✓  copy_local returns canonical URL
  ✓  preview exists in bucket
  ✓  oversize upload rejected with 413

────────────────────────────────────────────────────────────
  Cleanup — DynamoDB
────────────────────────────────────────────────────────────
  ✓  removed N DynamoDB smoke items

────────────────────────────────────────────────────────────
  Cleanup — S3
────────────────────────────────────────────────────────────
  ✓  removed 3 S3 smoke objects

────────────────────────────────────────────────────────────
  Result
────────────────────────────────────────────────────────────

  ✓  All checks passed. DynamoDB and S3 backends are verified.
```

Exit code 0 means everything works. Exit code 1 means at least one check
failed; the failures are printed to stderr.

## Step 5 — Configure the backend on the EC2 host

Once the smoke test passes, configure the running API process to use the cloud
backends. Start an SSM session:

```bash
aws ssm start-session \
  --target "$(terraform output -raw instance_id)" \
  --region "$(terraform output -raw aws_region)"
```

`bootstrap_instance.sh` already writes these values into `/etc/sketchscape.env`
(the `EnvironmentFile` of `sketchscape.service` and `sketchscape-worker.service`)
and reconciles them on every re-run. Inside the session, confirm and restart:

```bash
sudo grep -E 'SKETCHSCAPE_(STORAGE|DYNAMODB|ARTIFACTS)|AWS_REGION' /etc/sketchscape.env
sudo systemctl restart sketchscape.service
curl -s http://127.0.0.1:8000/health
```

The EC2 instance role already has the necessary IAM grants from the Terraform
apply — no additional credentials are needed.

## Troubleshooting

### AccessDeniedException on DynamoDB

The `aws_iam_role_policy.dynamodb_authoring` resource is attached to the EC2
instance role, not to your local CLI user. Running the smoke test locally uses
your CLI credentials. Ensure your local IAM user/role has `dynamodb:*` or at
minimum `GetItem`, `PutItem`, `DeleteItem`, `Query`, `DescribeTable` on the
table ARN.

Quick check:

```bash
aws dynamodb describe-table --table-name "$TABLE" --region "$REGION"
```

If that returns a table description, your credentials have sufficient access.

### AccessDenied on S3

Similarly, your local credentials need `s3:PutObject`, `s3:GetObject`,
`s3:DeleteObject`, `s3:ListBucket` (for cleanup), and `s3:GetObject` on the
bucket. Check:

```bash
aws s3 ls "s3://$BUCKET/artifacts/" --region "$REGION"
```

### Smoke test items not cleaned up

If the script exits before cleanup (e.g. a keyboard interrupt), clean up
manually:

```bash
# DynamoDB: delete all PROJECT#smoke-* and ASSET#smoke-* items
aws dynamodb scan \
  --table-name "$TABLE" \
  --filter-expression "begins_with(pk, :prefix)" \
  --expression-attribute-values '{":prefix":{"S":"smoke-"}}' \
  --region "$REGION" \
  --query "Items[*].{pk:pk.S,sk:sk.S}"

# S3: remove all smoke-* job artifacts
aws s3 rm "s3://$BUCKET/artifacts/" --recursive \
  --exclude "*" --include "*smoke-*" --region "$REGION"
```

## Teardown

To remove the DynamoDB table and S3 bucket later:

1. Empty the artifacts bucket (Terraform will refuse to destroy a non-empty
   bucket):
   ```bash
   aws s3 rm "s3://$BUCKET" --recursive --region "$REGION"
   ```

2. Remove the deletion-protection resource policy from the DynamoDB table:
   ```bash
   aws dynamodb delete-resource-policy \
     --resource-arn "$(terraform output -raw dynamodb_table_arn)" \
     --region "$REGION"
   ```

3. Set both flags back to false and apply:
   ```bash
   # in terraform.tfvars:
   enable_dynamodb         = false
   enable_artifacts_bucket = false
   ```
   ```bash
   cd infra/aws
   terraform plan   # review: should show 9 resources to destroy
   terraform apply
   ```
