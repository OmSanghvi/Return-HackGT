# SketchScape AWS GPU deployment

This is a deliberately small, cost-controlled deployment for the hackathon:
one GPU EC2 instance runs the FastAPI backend and accepts exactly one job at a
time. For each job it runs **local SAM 3.1** concept segmentation from the
short `subject_hint`, releases SAM memory, then runs staged Fast-SAM3D and
returns its Gaussian-splat PLY.

It uses no paid SAM 3.1 API. AWS credits still pay for the GPU instance while
it is running.

## Before creating anything

1. Request access to both gated Hugging Face models: `facebook/sam-3d-objects`
   and `facebook/sam3.1`.
2. Install and authenticate the AWS CLI locally: `aws sts get-caller-identity`
   must succeed.
3. Confirm your AWS account has quota and on-demand capacity for the selected
   GPU in the chosen region. `g4dn.xlarge` is the low-cost 16 GiB T4 baseline.
   `g5.xlarge` and `g6.xlarge` provide about 23 GiB usable GPU memory but still
   have only 16 GiB host RAM. For the persistent warm-worker path, use
   `g6e.xlarge`: one L40S with about 46 GiB usable GPU memory and 32 GiB host
   RAM while remaining within a four-vCPU G/VT quota.
4. Copy `terraform.tfvars.example` to `terraform.tfvars`, replace
   `allowed_cidr` with the current public IP of the network Unity will use,
   and never commit that file.

## Create, copy, bootstrap

First run the repository's read-only prerequisite check from the project root:

```bash
./scripts/aws_preflight.sh
```

Then, from this folder:

```bash
terraform init
terraform plan
terraform apply
./publish_bundle.sh
```

The instance schedules a 30-minute auto-stop timer (`auto_stop_minutes`) on
every boot as a compute-cost circuit breaker. A persistent systemd service
reinstalls the timer after later EC2 starts; it is independent of AWS Budget
alerts. For a longer bootstrap, cancel it from the EC2 shell with
`sudo shutdown -c` and immediately schedule a new bounded timer, for example
`sudo shutdown -h +120`.

Wait for the command printed by `publish_bundle.sh` to complete, then start a
secure AWS Systems Manager shell (no SSH port or key is needed):

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)" --region "$(terraform output -raw aws_region)"
```

Inside that EC2 shell, enter the approved Hugging Face token only for the
one-time gated model download, then bootstrap:

```bash
export HF_TOKEN='hf_...'
sudo -E bash /opt/sketchscape/infra/aws/bootstrap_instance.sh
unset HF_TOKEN
curl http://127.0.0.1:8000/health
```

The bootstrap builds two **separate** virtual environments. It can take a
while because Fast-SAM3D compiles/install dependencies and downloads model
weights. Do not interrupt it; it writes readiness markers only after each
environment passes an import preflight.

Outside the instance, test `$(terraform output -raw api_url)/health`, then
point Unity to `$(terraform output -raw api_url)`. Submit the image with a
short `subject_hint`, for example `blue backpack`. The prompt is a noun phrase
for SAM 3.1, not a full instruction.

## Cost guardrails

The GPU bills while the instance is **running**, even while idle. Stop it after
testing; the EBS volume retains the completed environments and model weights:

```bash
$(terraform output -raw stop_command)
```

Restart later from the AWS console or:

```bash
aws ec2 start-instances --instance-ids "$(terraform output -raw instance_id)" --region "$(terraform output -raw aws_region)"
```

Stopping retains small EBS and Elastic-IP charges. Run `terraform destroy`
when the project is done; it deletes this stack and its root volume. The
private code-staging bucket is deleted only when empty; Terraform refuses to
destroy it if it still contains a release bundle, so remove the bundle first
only after you have saved the source elsewhere.

## Durable authoring storage (off by default)

Set `enable_dynamodb = true` in `terraform.tfvars` to provision the authoring
table, and/or `enable_artifacts_bucket = true` to provision the PLY/mask/preview
bucket. Both default to `false` to prevent accidental spend.

```bash
# terraform.tfvars
enable_dynamodb         = true
enable_artifacts_bucket = true
```

After `terraform apply`, configure the backend process on the EC2 host:

```bash
# /opt/sketchscape/backend/.env  (on the EC2 host only, never commit this)
SKETCHSCAPE_STORAGE_BACKEND=dynamodb
SKETCHSCAPE_DYNAMODB_TABLE=<terraform output -raw dynamodb_table_name>
AWS_REGION=<terraform output -raw aws_region>
# Future slice: once artifact storage is migrated to S3
# SKETCHSCAPE_ARTIFACTS_BUCKET=<terraform output -raw artifacts_bucket>
```

The EC2 instance role receives the necessary IAM grants automatically when the
flags are enabled; no additional credentials are needed on the host.

### Storage and artifact backends on the EC2 host

After apply, set all three backends in the host `.env`. The instance role gains
access to both AWS services automatically from the Terraform IAM grants:

```bash
# /opt/sketchscape/backend/.env  (on EC2 host only)
SKETCHSCAPE_STORAGE_BACKEND=dynamodb
SKETCHSCAPE_DYNAMODB_TABLE=<terraform output -raw dynamodb_table_name>
SKETCHSCAPE_ARTIFACTS_BACKEND=s3
SKETCHSCAPE_ARTIFACTS_BUCKET=<terraform output -raw artifacts_bucket>
AWS_REGION=<terraform output -raw aws_region>
```

For a local or demo deployment without AWS, keep both backends at their
defaults (`local`) — no env vars are needed.

### DynamoDB table layout

The authoring table uses a single-table `pk`/`sk` design matching
`backend/storage.py`:

| pk | sk | stores |
|----|----|--------|
| `PROJECT#<project_id>` | `META` | project record |
| `PROJECT#<project_id>` | `BLUEPRINT#<0-padded revision>` | one blueprint revision |
| `PROJECT#<project_id>` | `PUBLICATION#<0-padded sequence>` | one append-only publication record |
| `ASSET#<asset_id>` | `META` | catalog asset |

Zero-padded sort keys keep `Query` results in creation order without a sort.
The table has PITR (35-day continuous restore) and AES-256 server-side
encryption enabled. A resource policy blocks `DeleteTable` for all principals
except the account root; remove it before running `terraform destroy`.

### Artifacts bucket

The artifacts bucket stores PLY, mask, and preview files under an
`artifacts/` prefix. The EC2 instance role can only read/write that prefix —
it cannot list the bucket or touch other objects. Object versioning is enabled
with a 30-day noncurrent-version expiry so accidental overwrites are
recoverable without indefinite storage growth.

The backend currently writes artifacts to the EC2 local filesystem. Migrating
them to S3 is a future roadmap slice; provisioning the bucket now means that
slice won't require another Terraform apply.

## Limits

This is a hackathon deployment, not a resilient production platform. Never
expose port 8000 to `0.0.0.0/0`; update `allowed_cidr` for the demo network
and run `terraform apply` before the event. A production version would separate
API/worker, add TLS termination and client authentication, and use the
DynamoDB/S3 backends described above for every replica.
