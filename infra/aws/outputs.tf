output "instance_id" {
  value       = aws_instance.gpu.id
  description = "Use this with AWS Systems Manager Session Manager; no SSH key is created."
}

output "api_url" {
  value       = "http://${aws_eip.api.public_ip}:8000"
  description = "Add /docs after bootstrap to verify the private demo API."
}

output "bundle_bucket" {
  value       = aws_s3_bucket.bundle.id
  description = "Private staging bucket used only to copy this workspace to the EC2 host."
}

output "aws_region" {
  value = var.aws_region
}

output "stop_command" {
  value       = "aws ec2 stop-instances --instance-ids ${aws_instance.gpu.id} --region ${var.aws_region}"
  description = "Run immediately after testing; stopping ends GPU instance charges."
}

output "dynamodb_table_name" {
  value       = var.enable_dynamodb ? aws_dynamodb_table.authoring[0].name : null
  description = "Set SKETCHSCAPE_DYNAMODB_TABLE to this value on the EC2 host when using SKETCHSCAPE_STORAGE_BACKEND=dynamodb."
}

output "dynamodb_table_arn" {
  value       = var.enable_dynamodb ? aws_dynamodb_table.authoring[0].arn : null
  description = "ARN of the authoring table; used to scope additional IAM policies."
}

output "artifacts_bucket" {
  value       = var.enable_artifacts_bucket ? aws_s3_bucket.artifacts[0].id : null
  description = "S3 bucket name for PLY/mask/preview artifacts. Set SKETCHSCAPE_ARTIFACTS_BUCKET to this value on the EC2 host when artifact storage is migrated to S3."
}

output "artifacts_bucket_arn" {
  value       = var.enable_artifacts_bucket ? aws_s3_bucket.artifacts[0].arn : null
  description = "ARN of the artifacts bucket; used to scope additional IAM policies."
}
