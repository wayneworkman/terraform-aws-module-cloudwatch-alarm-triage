# Lambda that intentionally fails due to missing permissions
resource "aws_lambda_function" "demo_failing_lambda" {
  filename         = data.archive_file.failing_lambda.output_path
  function_name    = join("-", compact([var.prefix, "ec2-lister"]))
  role            = aws_iam_role.restricted_lambda_role.arn
  handler         = "index.handler"
  runtime         = "python3.13"
  timeout         = 10
  memory_size     = 128
  
  environment {
    variables = {
      PURPOSE = "Demo - Intentional failure for triage testing"
    }
  }
  
  # Ensure the triage module is fully deployed first
  depends_on = [time_sleep.wait_for_module]
  
  tags = {
    Environment = "Demo"
    Purpose     = "Failing Lambda for triage testing"
  }
}

# EventBridge rule to trigger Lambda every minute
resource "aws_cloudwatch_event_rule" "every_minute" {
  name                = join("-", compact([var.prefix, "every-minute"]))
  description         = "Trigger failing lambda every minute for demo"
  schedule_expression = "rate(1 minute)"
  
  # Can be toggled on/off for testing
  state = var.enable_demo_failures ? "ENABLED" : "DISABLED"
  
  depends_on = [time_sleep.wait_for_module]
  
  tags = {
    Environment = "Demo"
    Purpose     = "EventBridge rule for demo failures"
  }
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.every_minute.name
  target_id = "FailingLambdaTarget"
  arn       = aws_lambda_function.demo_failing_lambda.arn
  
  # Add retry configuration to handle initial setup delays
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }
  
  depends_on = [
    aws_lambda_function.demo_failing_lambda,
    aws_lambda_permission.allow_eventbridge
  ]
}

# Permission for EventBridge to invoke the Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.demo_failing_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_minute.arn
}

# IAM role with NO EC2 permissions (intentionally restrictive)
resource "aws_iam_role" "restricted_lambda_role" {
  name = join("-", compact([var.prefix, "restricted-lambda-role"]))
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
  
  tags = {
    Environment = "Demo"
    Purpose     = "Restricted IAM role for failing Lambda"
  }
}

# Only basic Lambda execution permissions - NO EC2 access
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.restricted_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Data source for the failing Lambda code
data "archive_file" "failing_lambda" {
  type        = "zip"
  output_path = "/tmp/demo-failing-lambda-${random_id.demo_lambda_hash.hex}.zip"
  
  source {
    content  = file("${path.module}/lambda_code/failing_lambda.py")
    filename = "index.py"
  }
}

resource "random_id" "demo_lambda_hash" {
  keepers = {
    lambda_code = filemd5("${path.module}/lambda_code/failing_lambda.py")
  }
  byte_length = 8
}