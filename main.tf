data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  resource_name_prefix = var.resource_prefix != "" ? "${var.resource_prefix}-" : ""
  resource_name_suffix = var.resource_suffix != "" ? "-${var.resource_suffix}" : ""
}

resource "aws_dynamodb_table" "alarm_investigations" {
  name           = "${local.resource_name_prefix}alarm-investigations${local.resource_name_suffix}"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "alarm_name"
  
  attribute {
    name = "alarm_name"
    type = "S"
  }
  
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
  
  tags = var.tags
}

# Random suffix for S3 bucket uniqueness
resource "random_string" "bucket_suffix" {
  length  = 4
  special = false
  upper   = false
  numeric = true
  lower   = true
}

# S3 bucket for investigation reports
resource "aws_s3_bucket" "investigation_reports" {
  bucket = "${local.resource_name_prefix}alarm-reports-${random_string.bucket_suffix.result}"
  
  tags = var.tags
}

# Enable versioning
resource "aws_s3_bucket_versioning" "investigation_reports" {
  bucket = aws_s3_bucket.investigation_reports.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Enable encryption with SSE-S3
resource "aws_s3_bucket_server_side_encryption_configuration" "investigation_reports" {
  bucket = aws_s3_bucket.investigation_reports.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "investigation_reports" {
  bucket = aws_s3_bucket.investigation_reports.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Optional access logging
resource "aws_s3_bucket_logging" "investigation_reports" {
  count = var.reports_bucket_logging != null ? 1 : 0
  
  bucket = aws_s3_bucket.investigation_reports.id
  
  target_bucket = var.reports_bucket_logging.target_bucket
  target_prefix = var.reports_bucket_logging.target_prefix
}

# Optional lifecycle configuration
resource "aws_s3_bucket_lifecycle_configuration" "investigation_reports" {
  count = var.reports_bucket_lifecycle_days != null ? 1 : 0
  
  bucket = aws_s3_bucket.investigation_reports.id
  
  rule {
    id     = "delete-old-reports"
    status = "Enabled"
    
    # Delete current versions after specified days
    expiration {
      days = var.reports_bucket_lifecycle_days
    }
    
    # Delete non-current versions after specified days
    noncurrent_version_expiration {
      noncurrent_days = var.reports_bucket_lifecycle_days
    }
  }
}

resource "random_id" "lambda_hash" {
  keepers = {
    triage_handler = filemd5("${path.module}/lambda/triage_handler.py")
    bedrock_client = filemd5("${path.module}/lambda/bedrock_client.py")
    prompt_template = filemd5("${path.module}/lambda/prompt_template.py")
  }
  byte_length = 8
}

resource "aws_cloudwatch_log_group" "triage_lambda" {
  name              = "/aws/lambda/${local.resource_name_prefix}triage-handler${local.resource_name_suffix}"
  retention_in_days = 7
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "tool_lambda" {
  name              = "/aws/lambda/${local.resource_name_prefix}tool-lambda${local.resource_name_suffix}"
  retention_in_days = 7
  tags              = var.tags
}

resource "aws_iam_role" "triage_lambda_role" {
  name = "${local.resource_name_prefix}triage-role${local.resource_name_suffix}"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = [
            "lambda.amazonaws.com",
            "lambda.alarms.cloudwatch.amazonaws.com"
          ]
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
  
  tags = var.tags
}

resource "aws_iam_role_policy" "triage_lambda_policy" {
  name = "${local.resource_name_prefix}triage-policy${local.resource_name_suffix}"
  role = aws_iam_role.triage_lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.tool_lambda.arn
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = var.sns_topic_arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.alarm_investigations.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.investigation_reports.arn}/*"
      }
    ]
  })
}

resource "aws_iam_role" "tool_lambda_role" {
  name = "${local.resource_name_prefix}tool-role${local.resource_name_suffix}"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "tool_lambda_readonly" {
  role       = aws_iam_role.tool_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy_attachment" "tool_lambda_basic" {
  role       = aws_iam_role.tool_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "tool_lambda_deny_policy" {
  name = "${local.resource_name_prefix}tool-deny-policy${local.resource_name_suffix}"
  role = aws_iam_role.tool_lambda_role.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Deny"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "dynamodb:GetItem",
          "dynamodb:BatchGetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "secretsmanager:GetSecretValue",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ssm:ParameterType": "SecureString"
          }
        }
      },
      {
        Effect = "Deny"
        Action = [
          "secretsmanager:*"
        ]
        Resource = "*"
      }
    ]
  })
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "/tmp/triage-lambda-${random_id.lambda_hash.hex}.zip"
}

resource "aws_lambda_function" "triage_handler" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${local.resource_name_prefix}triage-handler${local.resource_name_suffix}"
  role            = aws_iam_role.triage_lambda_role.arn
  handler         = "triage_handler.handler"
  runtime         = "python3.13"
  timeout         = var.lambda_timeout
  memory_size     = var.lambda_memory_size
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  
  environment {
    variables = {
      BEDROCK_MODEL_ID            = var.bedrock_model_id
      TOOL_LAMBDA_ARN             = aws_lambda_function.tool_lambda.arn
      SNS_TOPIC_ARN               = var.sns_topic_arn
      BEDROCK_REGION              = data.aws_region.current.region
      DYNAMODB_TABLE              = aws_dynamodb_table.alarm_investigations.name
      INVESTIGATION_WINDOW_HOURS  = tostring(var.investigation_window_hours)
      REPORTS_BUCKET              = aws_s3_bucket.investigation_reports.id
    }
  }
  
  depends_on = [
    aws_cloudwatch_log_group.triage_lambda,
    aws_iam_role_policy.triage_lambda_policy
  ]
  
  tags = var.tags
}

data "archive_file" "tool_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/tool-lambda"
  output_path = "/tmp/tool-lambda-${random_id.lambda_hash.hex}.zip"
}

resource "aws_lambda_function" "tool_lambda" {
  filename         = data.archive_file.tool_lambda_zip.output_path
  function_name    = "${local.resource_name_prefix}tool-lambda${local.resource_name_suffix}"
  role            = aws_iam_role.tool_lambda_role.arn
  handler         = "tool_handler.handler"
  runtime         = "python3.13"
  timeout         = var.tool_lambda_timeout
  memory_size     = var.tool_lambda_memory_size
  source_code_hash = data.archive_file.tool_lambda_zip.output_base64sha256
  
  reserved_concurrent_executions = var.tool_lambda_reserved_concurrency == -1 ? null : var.tool_lambda_reserved_concurrency
  
  
  depends_on = [
    aws_cloudwatch_log_group.tool_lambda,
    aws_iam_role_policy.tool_lambda_deny_policy,
    aws_iam_role_policy_attachment.tool_lambda_readonly
  ]
  
  tags = var.tags

  environment {
    variables = {
      BEDROCK_REGION       = data.aws_region.current.region
    }
  }
}

resource "aws_lambda_permission" "allow_orchestrator" {
  statement_id  = "AllowExecutionFromOrchestrator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tool_lambda.function_name
  principal     = aws_iam_role.triage_lambda_role.arn
}

resource "aws_lambda_permission" "allow_cloudwatch_alarms" {
  statement_id  = "AllowExecutionFromCloudWatchAlarms"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.triage_handler.function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
}