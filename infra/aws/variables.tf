variable "aws_region" {
  description = "AWS region with the requested GPU capacity."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for AWS resources."
  type        = string
  default     = "sketchscape"
}

variable "instance_type" {
  description = "Single GPU host. g4dn.xlarge is the low-cost T4 baseline; g5.xlarge and g6.xlarge add GPU memory; g6e.xlarge adds an L40S plus 32 GiB host RAM for the warm-worker path."
  type        = string
  default     = "g4dn.xlarge"

  validation {
    condition     = contains(["g4dn.xlarge", "g5.xlarge", "g6.xlarge", "g6e.xlarge"], var.instance_type)
    error_message = "Use g4dn.xlarge, g5.xlarge, g6.xlarge, or g6e.xlarge. Larger sizes require an EC2 G/VT vCPU quota increase."
  }
}

variable "allowed_cidr" {
  description = "Public IPv4 CIDR allowed to reach the demo API, normally your current public IP with /32."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.allowed_cidr)) && var.allowed_cidr != "0.0.0.0/0"
    error_message = "Set allowed_cidr to a restricted IPv4 CIDR such as 203.0.113.10/32. 0.0.0.0/0 is forbidden."
  }
}

variable "root_volume_gib" {
  description = "Persistent encrypted EBS space for both model environments, checkpoints, and artifacts."
  type        = number
  default     = 120

  validation {
    condition     = var.root_volume_gib >= 100
    error_message = "Use at least 100 GiB; SAM 3.1, Fast-SAM3D, CUDA wheels, and checkpoints are large."
  }
}

variable "auto_stop_minutes" {
  description = "Hard safety timer installed at boot. The EC2 instance stops itself after this many minutes unless cancelled from the instance."
  type        = number
  default     = 30

  validation {
    condition     = var.auto_stop_minutes >= 10 && var.auto_stop_minutes <= 240
    error_message = "Choose an auto-stop timer between 10 and 240 minutes."
  }
}

variable "enable_dynamodb" {
  description = "Provision the DynamoDB authoring table (<project_name>-authoring). Set to true only when ready to accept ongoing DynamoDB costs. PAY_PER_REQUEST charges scale with actual reads/writes; stays near the free tier at low QPS, but is never completely free. Remove the deletion-protection policy before destroying the stack."
  type        = bool
  default     = false
}

variable "enable_artifacts_bucket" {
  description = "Provision the S3 artifacts bucket for PLY/mask/preview files. Set to true only when ready to migrate artifact storage from the EC2 local disk to S3. The bucket is versioned with 30-day noncurrent expiry. force_destroy is false, so Terraform refuses to delete a non-empty bucket — empty it manually before destroying the stack."
  type        = bool
  default     = false
}
