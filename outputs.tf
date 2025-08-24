output "triage_lambda_arn" {
  description = "ARN of the triage Lambda function for use in CloudWatch Alarm actions"
  value       = aws_lambda_function.triage_handler.arn
}

output "triage_lambda_function_name" {
  description = "Name of the triage Lambda function"
  value       = aws_lambda_function.triage_handler.function_name
}

output "tool_lambda_arn" {
  description = "ARN of the tool Lambda function used by Claude"
  value       = aws_lambda_function.tool_lambda.arn
}

output "tool_lambda_function_name" {
  description = "Name of the tool Lambda function"
  value       = aws_lambda_function.tool_lambda.function_name
}

output "triage_lambda_role_arn" {
  description = "ARN of the IAM role used by the triage Lambda"
  value       = aws_iam_role.triage_lambda_role.arn
}

output "tool_lambda_role_arn" {
  description = "ARN of the IAM role used by the tool Lambda"
  value       = aws_iam_role.tool_lambda_role.arn
}

output "triage_lambda_log_group" {
  description = "CloudWatch Logs group for the triage Lambda"
  value       = aws_cloudwatch_log_group.triage_lambda.name
}

output "tool_lambda_log_group" {
  description = "CloudWatch Logs group for the tool Lambda"
  value       = aws_cloudwatch_log_group.tool_lambda.name
}

output "bedrock_model_id" {
  description = "The Bedrock model ID being used"
  value       = var.bedrock_model_id
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table for deduplication"
  value       = aws_dynamodb_table.alarm_investigations.name
}

output "reports_bucket_name" {
  description = "Name of the S3 bucket storing investigation reports"
  value       = aws_s3_bucket.investigation_reports.id
}

output "reports_bucket_arn" {
  description = "ARN of the S3 bucket storing investigation reports"
  value       = aws_s3_bucket.investigation_reports.arn
}