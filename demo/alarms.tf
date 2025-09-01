# CloudWatch Log Group for failing Lambda (created explicitly for proper ordering)
resource "aws_cloudwatch_log_group" "demo_lambda_logs" {
  name              = "/aws/lambda/${join("-", compact([var.prefix, "ec2-lister"]))}"
  retention_in_days = 7
  
  tags = {
    Environment = "Demo"
    Purpose     = "Logs for failing Lambda demo"
  }
}

# Alarm for Lambda errors - triggers on 1 failure, clears on 1 success
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = join("-", compact([var.prefix, "lambda-errors"]))
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"  # Trigger/clear with just 1 occurrence
  metric_name        = "Errors"
  namespace          = "AWS/Lambda"
  period             = "60"
  statistic          = "Sum"
  threshold          = "0"  # Any errors (>0) will trigger
  alarm_description  = "Triggers immediately on any Lambda error, clears immediately when errors stop"
  
  dimensions = {
    FunctionName = aws_lambda_function.demo_failing_lambda.function_name
  }
  
  # Actions when entering ALARM state
  alarm_actions = [module.cloudwatch_triage.triage_lambda_arn]
  
  # Don't trigger investigation when returning to OK state
  ok_actions = []
  
  # Actions when there's insufficient data
  insufficient_data_actions = []
  
  # Important: This ensures the alarm clears when errors stop
  treat_missing_data = "notBreaching"
  
  # Ensure module is deployed before creating alarm
  depends_on = [
    module.cloudwatch_triage,
    aws_lambda_function.demo_failing_lambda,
    aws_lambda_permission.allow_cloudwatch
  ]
  
  tags = {
    Environment = "Demo"
    Purpose     = "CloudWatch alarm for Lambda errors"
  }
}

# Only one alarm needed for testing - removed the error rate alarm