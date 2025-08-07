# Additional demo scenarios (commented out by default)
# Uncomment and modify as needed to test different failure types

# Example 2: Lambda Timeout Scenario
# resource "aws_lambda_function" "timeout_demo" {
#   filename         = data.archive_file.timeout_lambda.output_path
#   function_name    = join("-", compact([var.prefix, "timeout-demo"]))
#   role            = aws_iam_role.basic_lambda_role.arn
#   handler         = "index.handler"
#   runtime         = "python3.13"
#   timeout         = 5  # Short timeout to force timeouts
#   memory_size     = 128
#   
#   environment {
#     variables = {
#       PURPOSE = "Demo - Lambda timeout scenario"
#       SLOW_OPERATION_DURATION = "10"  # Longer than timeout
#     }
#   }
# }

# data "archive_file" "timeout_lambda" {
#   type        = "zip"
#   output_path = "/tmp/timeout-lambda-${random_id.timeout_hash.hex}.zip"
#   
#   source {
#     content = <<-EOF
# import time
# import os
# 
# def handler(event, context):
#     """Simulates a Lambda that times out due to slow operations."""
#     duration = int(os.environ.get('SLOW_OPERATION_DURATION', '10'))
#     print(f"Starting slow operation that will take {duration} seconds...")
#     
#     # This will cause the Lambda to timeout (duration > timeout)
#     time.sleep(duration)
#     
#     return {
#         'statusCode': 200,
#         'body': 'Operation completed successfully'
#     }
# EOF
#     filename = "index.py"
#   }
# }

# resource "random_id" "timeout_hash" {
#   keepers = {
#     code_change = "timeout-demo-v1"
#   }
#   byte_length = 8
# }

# Example 3: Memory Exhaustion Scenario
# resource "aws_lambda_function" "memory_demo" {
#   filename         = data.archive_file.memory_lambda.output_path
#   function_name    = join("-", compact([var.prefix, "memory-demo"]))
#   role            = aws_iam_role.basic_lambda_role.arn
#   handler         = "index.handler"
#   runtime         = "python3.13"
#   timeout         = 30
#   memory_size     = 128  # Low memory to trigger exhaustion
# }

# data "archive_file" "memory_lambda" {
#   type        = "zip"
#   output_path = "/tmp/memory-lambda-${random_id.memory_hash.hex}.zip"
#   
#   source {
#     content = <<-EOF
# import json
# 
# def handler(event, context):
#     """Simulates memory exhaustion by creating large objects."""
#     print("Starting memory-intensive operation...")
#     
#     # Create increasingly large lists until memory runs out
#     data = []
#     try:
#         for i in range(100):
#             # Each iteration adds ~10MB of data
#             large_data = ['x' * 10000] * 1000
#             data.append(large_data)
#             print(f"Iteration {i}: Memory usage increasing...")
#             
#         return {
#             'statusCode': 200,
#             'body': json.dumps(f'Processed {len(data)} iterations')
#         }
#     except MemoryError:
#         raise Exception("Lambda ran out of memory during processing")
# EOF
#     filename = "index.py"
#   }
# }

# resource "random_id" "memory_hash" {
#   keepers = {
#     code_change = "memory-demo-v1"
#   }
#   byte_length = 8
# }

# Basic IAM role for additional scenarios
# resource "aws_iam_role" "basic_lambda_role" {
#   name = join("-", compact([var.prefix, "basic-lambda-role"]))
#   
#   assume_role_policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [{
#       Action = "sts:AssumeRole"
#       Effect = "Allow"
#       Principal = {
#         Service = "lambda.amazonaws.com"
#       }
#     }]
#   })
# }

# resource "aws_iam_role_policy_attachment" "basic_lambda_execution" {
#   role       = aws_iam_role.basic_lambda_role.name
#   policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
# }

# Instructions for enabling additional scenarios:
# 1. Uncomment the desired scenario(s) above
# 2. Add corresponding CloudWatch alarms
# 3. Add EventBridge rules to trigger the scenarios
# 4. Run terraform apply to deploy

# Example alarm for timeout scenario:
# resource "aws_cloudwatch_metric_alarm" "timeout_alarm" {
#   alarm_name          = join("-", compact([var.prefix, "timeout-alarm"]))
#   comparison_operator = "GreaterThanThreshold"
#   evaluation_periods  = "1"
#   metric_name        = "Duration" 
#   namespace          = "AWS/Lambda"
#   period             = "60"
#   statistic          = "Average"
#   threshold          = "4000"  # 4 seconds (close to 5 second timeout)
#   
#   dimensions = {
#     FunctionName = aws_lambda_function.timeout_demo.function_name
#   }
#   
#   alarm_actions = [module.cloudwatch_triage.triage_lambda_arn]
# }