output "triage_lambda_arn" {
  description = "ARN of the triage Lambda - use this in your CloudWatch Alarms"
  value       = module.cloudwatch_triage.triage_lambda_arn
}

output "triage_lambda_log_group" {
  description = "CloudWatch Logs group for monitoring investigations"
  value       = module.cloudwatch_triage.triage_lambda_log_group
}

output "tool_lambda_arn" {
  description = "ARN of the tool Lambda used by Claude"
  value       = module.cloudwatch_triage.tool_lambda_arn
}

output "tool_lambda_log_group" {
  description = "CloudWatch Logs group for tool Lambda"
  value       = module.cloudwatch_triage.tool_lambda_log_group
}

output "demo_failing_lambda_name" {
  description = "Name of the demo Lambda that intentionally fails"
  value       = aws_lambda_function.demo_failing_lambda.function_name
}

output "demo_failing_lambda_arn" {
  description = "ARN of the demo Lambda that intentionally fails"
  value       = aws_lambda_function.demo_failing_lambda.arn
}

output "demo_alarm_name" {
  description = "Name of the demo CloudWatch Alarm"
  value       = aws_cloudwatch_metric_alarm.lambda_errors.alarm_name
}

output "demo_alarm_arn" {
  description = "ARN of the demo CloudWatch Alarm"
  value       = aws_cloudwatch_metric_alarm.lambda_errors.arn
}

output "sns_topic_arn" {
  description = "ARN of the SNS topic for notifications"
  value       = aws_sns_topic.alarm_notifications.arn
}

output "demo_region" {
  description = "AWS region where the demo is deployed"
  value       = "us-east-2"
}

# Instructions for using the triage system
output "usage_instructions" {
  description = "Instructions for monitoring and using the demo"
  value = <<-EOT
    # Monitor alarm state changes:
    aws cloudwatch describe-alarms --alarm-names "${aws_cloudwatch_metric_alarm.lambda_errors.alarm_name}" --region us-east-2 --query "MetricAlarms[0].StateValue"
    
    # Manually trigger the alarm for testing (forces state transition):
    aws cloudwatch set-alarm-state --alarm-name "${aws_cloudwatch_metric_alarm.lambda_errors.alarm_name}" --state-value OK --state-reason "Reset for testing" --region us-east-2
    sleep 2
    aws cloudwatch set-alarm-state --alarm-name "${aws_cloudwatch_metric_alarm.lambda_errors.alarm_name}" --state-value ALARM --state-reason "Manual trigger for testing" --region us-east-2
    
    # Stop demo failures (alarm will clear in ~1 minute):
    aws events disable-rule --name "${aws_cloudwatch_event_rule.every_minute.name}" --region us-east-2
    
    # Restart demo failures (alarm will trigger in ~1 minute):
    aws events enable-rule --name "${aws_cloudwatch_event_rule.every_minute.name}" --region us-east-2
    
    # View triage Lambda logs:
    aws logs tail "${module.cloudwatch_triage.triage_lambda_log_group}" --region us-east-2 --follow
    
    # View tool Lambda logs:
    aws logs tail "${module.cloudwatch_triage.tool_lambda_log_group}" --region us-east-2 --follow
    
    # View failing Lambda logs:
    aws logs tail "/aws/lambda/${aws_lambda_function.demo_failing_lambda.function_name}" --region us-east-2 --follow
  EOT
}