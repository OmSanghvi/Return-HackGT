data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# A current AWS Deep Learning AMI supplies the NVIDIA driver. The application
# creates two isolated Python environments itself, so it does not rely on the
# AMI's bundled PyTorch version.
data "aws_ssm_parameter" "gpu_dlami" {
  name = "/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.8-ubuntu-24.04/latest/ami-id"
}

resource "aws_s3_bucket" "bundle" {
  bucket_prefix = "${var.project_name}-bundle-"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "bundle" {
  bucket                  = aws_s3_bucket.bundle.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bundle" {
  bucket = aws_s3_bucket.bundle.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_iam_role" "instance" {
  name_prefix = "${var.project_name}-ec2-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "bundle_read" {
  name_prefix = "${var.project_name}-bundle-read-"
  role        = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.bundle.arn}/releases/*"
    }]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name_prefix = "${var.project_name}-ec2-"
  role        = aws_iam_role.instance.name
}

resource "aws_security_group" "api" {
  name_prefix = "${var.project_name}-api-"
  description = "SketchScape public demo API; SSM removes the need for SSH ingress."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SketchScape API from the configured demo network"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-api" }
}

resource "aws_instance" "gpu" {
  ami                         = "ami-06134fbd1bcf1b066"
  instance_type               = var.instance_type
  subnet_id                   = "subnet-0dbcf749462aca710"
  vpc_security_group_ids      = [aws_security_group.api.id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true
  monitoring                  = true
  # If the boot safety timer shuts down Linux, keep the encrypted EBS volume
  # and stop GPU compute instead of terminating the instance.
  instance_initiated_shutdown_behavior = "stop"

  # Install a persistent boot service rather than scheduling only from the
  # first cloud-init run. Every later EC2 start receives the same bounded
  # shutdown guard; an operator can cancel and replace it for a longer test.
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    cat >/etc/systemd/system/sketchscape-auto-stop.service <<'UNIT'
    [Unit]
    Description=Schedule the SketchScape GPU cost-safety shutdown
    After=multi-user.target

    [Service]
    Type=oneshot
    ExecStart=/sbin/shutdown -h +${var.auto_stop_minutes}

    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload
    systemctl enable --now sketchscape-auto-stop.service
  EOF

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name    = "${var.project_name}-gpu-worker"
    Project = var.project_name
  }

  # A stopped instance with no auto-assigned public IP reads back as
  # associate_public_ip_address = false, which would force Terraform to
  # destroy and recreate the GPU host (and its model-bearing root volume).
  # Public reachability comes from aws_eip.api, so ignore that drift.
  lifecycle {
    ignore_changes = [associate_public_ip_address]
  }
}

resource "aws_eip" "api" {
  domain   = "vpc"
  instance = aws_instance.gpu.id
  tags     = { Name = "${var.project_name}-api" }
}

# ---------------------------------------------------------------------------
# Authoring durability: DynamoDB table + S3 artifacts bucket
#
# Both resources are off by default (count = 0) to prevent accidental spend.
# Set enable_dynamodb = true and/or enable_artifacts_bucket = true in
# terraform.tfvars once you are ready to provision them.
#
# No apply is automated; run `terraform plan` and review before `terraform apply`.
# ---------------------------------------------------------------------------

# -- DynamoDB authoring table -----------------------------------------------
#
# Single-table design matching the pk/sk layout in backend/storage.py:
#
#   PK = "PROJECT#<project_id>"  SK = "META"                        project record
#   PK = "PROJECT#<project_id>"  SK = "BLUEPRINT#<0-padded rev>"    blueprint revision
#   PK = "PROJECT#<project_id>"  SK = "PUBLICATION#<0-padded seq>"  append-only pub record
#   PK = "ASSET#<asset_id>"      SK = "META"                        catalog asset
#
# PAY_PER_REQUEST keeps costs proportional to actual usage, which is
# appropriate for a low-QPS hackathon deployment. PITR gives a 35-day
# continuous restore window so accidental deletes are recoverable.

resource "aws_dynamodb_table" "authoring" {
  count = var.enable_dynamodb ? 1 : 0

  name         = "${var.project_name}-authoring"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  # GSI1/GSI2 back Build Plan step 26's durable jobs and batch polling
  # (docs/DATA_ARCHITECTURE.md's "Indexes and table settings"). DynamoDbStore
  # refuses to start against a table missing either one -- see
  # storage.DynamoDbStore._check_required_indexes. NEEDS EXPLICIT APPROVAL
  # before `terraform apply` (Hard Rule 3): this diff is written, not applied.
  attribute {
    name = "gsi1pk"
    type = "S"
  }

  attribute {
    name = "gsi1sk"
    type = "S"
  }

  attribute {
    name = "gsi2pk"
    type = "S"
  }

  attribute {
    name = "gsi2sk"
    type = "S"
  }

  global_secondary_index {
    name            = "gsi1"
    hash_key        = "gsi1pk"
    range_key       = "gsi1sk"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "gsi2"
    hash_key        = "gsi2pk"
    range_key       = "gsi2sk"
    projection_type = "ALL"
  }

  # Link codes (step 18) and room-edit idempotency records (step 21) expire
  # via this attribute.
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name    = "${var.project_name}-authoring"
    Project = var.project_name
  }
}

# Prevent accidental table deletion while any published revision exists.
# Remove this resource before destroying the stack if you intend to tear down
# the table; do not blindly run `terraform destroy` on a table with live data.
resource "aws_dynamodb_resource_policy" "authoring_deny_delete" {
  count = var.enable_dynamodb ? 1 : 0

  resource_arn = aws_dynamodb_table.authoring[0].arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyTableDeleteExceptRoot"
      Effect    = "Deny"
      Principal = "*"
      Action    = "dynamodb:DeleteTable"
      Resource  = aws_dynamodb_table.authoring[0].arn
      Condition = {
        StringNotEquals = {
          "aws:PrincipalArn" = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
      }
    }]
  })
}

# -- S3 artifacts bucket ----------------------------------------------------
#
# Stores PLY, mask, and preview files produced by the GPU worker. This is
# separate from the bundle bucket (which stages the application code) so the
# two lifecycles and access patterns are independently controllable.
#
# The backend currently writes artifacts to the local filesystem. Migrating to
# S3 is a future durability slice; provisioning the bucket now lets that slice
# proceed without needing another Terraform apply.

resource "aws_s3_bucket" "artifacts" {
  count = var.enable_artifacts_bucket ? 1 : 0

  bucket_prefix = "${var.project_name}-artifacts-"
  # Do not force-destroy; PLY files may be referenced by published blueprints.
  force_destroy = false

  tags = {
    Name    = "${var.project_name}-artifacts"
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  count = var.enable_artifacts_bucket ? 1 : 0

  bucket                  = aws_s3_bucket.artifacts[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  count = var.enable_artifacts_bucket ? 1 : 0

  bucket = aws_s3_bucket.artifacts[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  count = var.enable_artifacts_bucket ? 1 : 0

  bucket = aws_s3_bucket.artifacts[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  count = var.enable_artifacts_bucket ? 1 : 0

  bucket = aws_s3_bucket.artifacts[0].id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# -- IAM grants to the EC2 instance role ------------------------------------
#
# Two narrowly-scoped inline policies added to the existing instance role.
# The GPU worker reads/writes only under the artifacts/ prefix; it cannot
# enumerate the bucket or touch other prefixes.

resource "aws_iam_role_policy" "dynamodb_authoring" {
  count = var.enable_dynamodb ? 1 : 0

  name_prefix = "${var.project_name}-dynamo-"
  role        = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AuthoringTableCRUD"
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:DescribeTable",
      ]
      # The base table ARN alone does not authorize Query calls that pass
      # IndexName=gsi1/gsi2 (storage.DynamoDbStore.list_project_jobs,
      # claim_next_job, release_expired_leases) -- IAM evaluates those against
      # the index's own ARN (".../index/<name>"), a distinct resource from the
      # table ARN. Without this, every GSI query is denied even though plain
      # pk/sk reads and writes work fine.
      Resource = [
        aws_dynamodb_table.authoring[0].arn,
        "${aws_dynamodb_table.authoring[0].arn}/index/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "artifacts_bucket" {
  count = var.enable_artifacts_bucket ? 1 : 0

  name_prefix = "${var.project_name}-artifacts-"
  role        = aws_iam_role.instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ArtifactsReadWrite"
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
      ]
      # Two prefixes in this bucket: artifacts/<job_id>/... (PLY/mask/preview
      # output, ArtifactStore.put/copy_local/serve) and
      # uploads/<project_id>/<upload_id>/... (source photos and masks,
      # ArtifactStore.put_upload/open_upload -- Build Plan step 26). Scoping
      # this policy to artifacts/* only denies every uploads/ call the worker
      # and API make once cloud storage is active.
      Resource = [
        "${aws_s3_bucket.artifacts[0].arn}/artifacts/*",
        "${aws_s3_bucket.artifacts[0].arn}/uploads/*",
      ]
    }]
  })
}

# Account ID is used in the table deletion-protection policy above.
data "aws_caller_identity" "current" {}
