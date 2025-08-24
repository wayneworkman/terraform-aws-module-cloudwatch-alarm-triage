# Demo provider configuration - uses us-east-2 where Claude Opus 4.1 is available
provider "aws" {
  region = "us-east-2"
}

# Deploy the CloudWatch Triage module
module "cloudwatch_triage" {
  source = "../"
  
  resource_prefix = var.prefix
  sns_topic_arn   = aws_sns_topic.alarm_notifications.arn
  
  # Claude Opus 4.1 configuration
  # Using the inference profile - IAM policy restricts to us-east-2 only
  # bedrock_model_id = "us.anthropic.claude-opus-4-1-20250805-v1:0"
  bedrock_model_id = "us.amazon.nova-premier-v1:0"
  
  tags = {
    Environment = "Demo"
    Purpose     = "CloudWatch Alarm Triage Testing"
  }
}

# SNS topic for notifications (created before module)
resource "aws_sns_topic" "alarm_notifications" {
  name = join("-", compact([var.prefix, "alarm-notifications"]))
  
  tags = {
    Environment = "Demo"
    Purpose     = "CloudWatch Alarm Notifications"
  }
}

# Email subscription for notifications
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarm_notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# Grant CloudWatch Alarms permission to invoke the triage Lambda
resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = module.cloudwatch_triage.triage_lambda_function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  
  depends_on = [module.cloudwatch_triage]
}

# Add a delay before starting the demo to ensure everything is ready
resource "time_sleep" "wait_for_module" {
  create_duration = "30s"
  
  depends_on = [
    module.cloudwatch_triage,
    aws_lambda_permission.allow_cloudwatch
  ]
}