output "ecr_repository_url" {
  value = aws_ecr_repository.migration.repository_url
}

output "batch_job_queue_name" {
  value = aws_batch_job_queue.migration.name
}

output "batch_job_definition_name" {
  value = aws_batch_job_definition.migration.name
}

output "secrets_manager_arn" {
  value = aws_secretsmanager_secret.credentials.arn
}

output "checkpoint_bucket" {
  value = aws_s3_bucket.checkpoints.bucket
}

output "checkpoint_uri" {
  value = "s3://${aws_s3_bucket.checkpoints.bucket}/checkpoint.json"
}

output "cloudwatch_log_group" {
  value = aws_cloudwatch_log_group.batch.name
}
