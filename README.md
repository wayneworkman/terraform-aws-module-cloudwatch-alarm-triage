# CloudWatch Alarm Triage with Claude Opus 4.1

Created by [Wayne Workman](https://github.com/wayneworkman)

[![GitHub](https://img.shields.io/badge/GitHub-wayneworkman-181717?logo=github)](https://github.com/wayneworkman)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Wayne_Workman-0077B5?logo=linkedin)](https://www.linkedin.com/in/wayne-workman-a8b37b353/)

## Overview

A reusable Terraform module that integrates AWS CloudWatch Alarms with AWS Bedrock's Claude Opus 4.1 in agent mode to automatically investigate and triage alarms. Claude operates as an agent with access to a tool Lambda function that executes AWS CLI commands and boto3 scripts, providing deep investigation capabilities. This solution provides engineers with comprehensive contextual information and preliminary analysis before they respond to incidents, significantly reducing mean time to resolution (MTTR).

**Critical Information**: 
- Claude Opus 4.1 model ID: `anthropic.claude-opus-4-1-20250805-v1:0`
- Available in select AWS regions including us-east-2
- Module uses the region of your calling Terraform provider

## Key Features

- **System Inference Profile**: Uses AWS-managed inference profile for reliable Claude Opus 4.1 invocation
- **Robust Error Handling**: Automatic retries with exponential backoff for API timeouts
- **5-Minute Read Timeout**: Extended timeout for handling complex investigations
- **50 Tool Call Iterations**: Supports thorough multi-step investigations
- **DynamoDB Deduplication**: Prevents duplicate investigations with configurable time window
- **Concurrent Execution Control**: Prevents overlapping investigations

## Architecture

### Two-Lambda Design

This module creates **two Lambda functions** working together:

1. **Orchestrator Lambda** (Python ZIP package)
   - Receives CloudWatch Alarm events
   - Invokes Claude Opus 4.1 in agent mode
   - Sends investigation results to SNS
   - Minimal IAM permissions (Bedrock, SNS, Logs)

2. **Tool Lambda** (ZIP package)
   - Called by Claude as a tool during investigation
   - Executes AWS CLI commands and boto3 scripts
   - Uses AWS managed `ReadOnlyAccess` policy with deny statements
   - Prevents access to sensitive data (S3 objects, DynamoDB data, secrets)

### Workflow

```
CloudWatch Alarm (ALARM state)
    ↓
Orchestrator Lambda
    ↓
DynamoDB Deduplication Check
    ↓ (if not recently investigated)
Claude Opus 4.1 (agent mode)
    ↓ (multiple tool calls)
Tool Lambda (AWS CLI + boto3)
    ↓ (returns findings)
Claude Analysis & Root Cause
    ↓
SNS Email Notification
```

### Deduplication

The module uses DynamoDB to prevent duplicate investigations of the same alarm within a configurable time window (default: 1 hour). This prevents multiple emails when CloudWatch continuously evaluates an alarm in ALARM state. The DynamoDB entries automatically expire using TTL.

## Module Structure

```
cloudwatch-alarm-triage/
├── main.tf                 # Core module resources
├── variables.tf            # Module input variables
├── outputs.tf              # Module outputs
├── versions.tf             # Provider version constraints
├── lambda/
│   ├── triage_handler.py   # Main Lambda function
│   ├── bedrock_client.py   # Bedrock integration
│   ├── prompt_template.py  # Claude prompt template
│   └── requirements.txt    # Python dependencies
├── tool-lambda/
│   └── tool_handler.py     # Tool Lambda handler
├── tests/
│   ├── unit/               # Unit tests (138 tests)
│   ├── integration/        # Integration tests
│   └── conftest.py         # Pytest configuration
├── demo/                   # Complete working example
│   ├── main.tf             # Demo deployment
│   ├── failing_lambda.tf   # Intentionally failing Lambda
│   ├── alarms.tf           # CloudWatch alarm config
│   ├── lambda_code/        # Demo Lambda code
│   ├── README.md           # Demo documentation
│   └── DEMO_SUMMARY.md     # Technical summary
└── README.md               # This file
```

## Quick Start

### 1. Deploy the Module

```hcl
# Configure provider for region with Claude Opus 4.1
provider "aws" {
  region = "us-east-2"  # or other supported region
}

module "cloudwatch_triage" {
  source = "path/to/cloudwatch-alarm-triage"
  
  sns_topic_arn = aws_sns_topic.alerts.arn
  resource_prefix = "prod"
  
  # Optional: Customize investigation
  bedrock_model_id = "anthropic.claude-opus-4-1-20250805-v1:0"
  investigation_depth = "comprehensive"
  max_tokens_per_investigation = 20000
  
  tags = {
    Environment = "Production"
    Owner       = "DevOps"
  }
}
```

### 2. Create SNS Topic

```hcl
resource "aws_sns_topic" "alerts" {
  name = "cloudwatch-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "oncall@example.com"
}
```
Be sure to click the "Confirmation" link in the email that SNS sends.


### 3. Configure CloudWatch Alarms

```hcl
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic           = "Sum"
  threshold           = "5"
  
  dimensions = {
    FunctionName = aws_lambda_function.app.function_name
  }
  
  # Add triage Lambda as alarm action
  alarm_actions = [module.cloudwatch_triage.triage_lambda_arn]
}
```

## Variables

### Required Variables

| Name | Description | Type |
|------|-------------|------|
| `sns_topic_arn` | ARN of the SNS topic for notifications | `string` |

### Optional Variables

| Name | Description | Type | Default |
|------|-------------|------|---------|
| `bedrock_model_id` | Bedrock Claude Opus 4.1 model identifier | `string` | `"anthropic.claude-opus-4-1-20250805-v1:0"` |
| `resource_prefix` | Prefix for all created resources | `string` | `""` |
| `resource_suffix` | Suffix for all created resources | `string` | `""` |
| `lambda_memory_size` | Memory allocation for orchestrator Lambda (MB) | `number` | `1024` |
| `tool_lambda_memory_size` | Memory allocation for tool Lambda (MB) | `number` | `2048` |
| `lambda_timeout` | Orchestrator Lambda timeout (seconds) | `number` | `900` |
| `tool_lambda_timeout` | Tool Lambda timeout (seconds) | `number` | `60` |
| `tool_lambda_reserved_concurrency` | Reserved concurrent executions for tool Lambda | `number` | `-1` (unlimited) |
| `investigation_depth` | Investigation depth (basic/detailed/comprehensive) | `string` | `"comprehensive"` |
| `max_tokens_per_investigation` | Maximum tokens for Claude response | `number` | `20000` |
| `investigation_window_hours` | Hours to wait before re-investigating same alarm | `number` | `1` |
| `tags` | Tags to apply to all resources | `map(string)` | `{}` |

## Outputs

| Name | Description |
|------|-------------|
| `triage_lambda_arn` | ARN of the triage Lambda function for use in CloudWatch Alarm actions |
| `triage_lambda_function_name` | Name of the triage Lambda function |
| `tool_lambda_arn` | ARN of the tool Lambda function used by Claude |
| `tool_lambda_function_name` | Name of the tool Lambda function |
| `triage_lambda_role_arn` | ARN of the IAM role used by the triage Lambda |
| `tool_lambda_role_arn` | ARN of the IAM role used by the tool Lambda |
| `triage_lambda_log_group` | CloudWatch Logs group for the triage Lambda |
| `tool_lambda_log_group` | CloudWatch Logs group for the tool Lambda |
| `bedrock_inference_profile_arn` | ARN of the system-defined Bedrock inference profile for Claude Opus 4.1 |
| `dynamodb_table_name` | Name of the DynamoDB table for deduplication |

## Investigation Capabilities

Claude can investigate alarms by executing:

### AWS CLI Commands
- `aws logs filter-log-events` - Analyze application logs
- `aws cloudwatch get-metric-statistics` - Review metric trends
- `aws iam get-role-policy` - Check permissions
- `aws cloudtrail lookup-events` - Find recent API calls
- `aws ec2 describe-instances` - Examine infrastructure
- `aws lambda get-function` - Review function configuration

### Python/boto3 Scripts
- Complex metric analysis across time ranges
- IAM policy evaluation and recommendations
- Resource configuration validation
- Cost analysis and optimization suggestions
- Pattern detection in logs and metrics

### Security Model

The tool Lambda uses:
- **AWS managed ReadOnlyAccess policy** for comprehensive resource inspection
- **Explicit deny statements** for sensitive data:
  - S3 object content (can list, cannot read)
  - DynamoDB data (can describe, cannot query)
  - Secrets Manager values (can list, cannot retrieve)
  - Parameter Store SecureString parameters (can list, cannot decrypt)

## Example Investigation Output

When a Lambda function alarm triggers, Claude might provide:

### 🚨 EXECUTIVE SUMMARY
Lambda function `prod-api-handler` experiencing 100% error rate due to missing DynamoDB table permissions. Immediate action required: Add `dynamodb:GetItem` permission to Lambda role.

### 🔍 INVESTIGATION DETAILS
**Commands executed:**
1. `aws logs filter-log-events --log-group-name /aws/lambda/prod-api-handler --start-time ...`
   - Found 47 AccessDenied errors in past 5 minutes
   - All errors: "User: arn:aws:sts::123456789012:assumed-role/lambda-role/prod-api-handler is not authorized to perform: dynamodb:GetItem on resource: arn:aws:dynamodb:us-east-2:123456789012:table/UserData"

2. `aws iam list-attached-role-policies --role-name lambda-role`
   - Only AWSLambdaBasicExecutionRole attached
   - No DynamoDB permissions found

3. `aws dynamodb describe-table --table-name UserData`
   - Table exists and is ACTIVE
   - No resource-level restrictions

### 📊 ROOT CAUSE
Lambda role lacks `dynamodb:GetItem` permission for the UserData table. This occurred after the recent IAM policy update that removed the overly permissive `*` resource access.

### 💥 IMPACT
- **Severity**: Critical - 100% of API requests failing
- **Users Affected**: All users attempting to access profile data
- **Business Impact**: Complete service outage for user profile features
- **Duration**: Started 6 minutes ago, ongoing

### 🔧 IMMEDIATE ACTIONS
1. **Grant DynamoDB permission** (ETA: 2 minutes):
```bash
aws iam put-role-policy --role-name lambda-role --policy-name DynamoDBAccess --policy-document '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem", "dynamodb:Query"],
    "Resource": "arn:aws:dynamodb:us-east-2:123456789012:table/UserData"
  }]
}'
```

2. **Verify fix**:
```bash
aws lambda invoke --function-name prod-api-handler --payload '{"test": "true"}' response.json
```

### 🛡️ PREVENTION
- **Infrastructure as Code**: Include DynamoDB permissions in Terraform/CloudFormation
- **Pre-deployment Testing**: Add integration tests that verify all required permissions
- **IAM Policy Review**: Implement approval process for IAM changes affecting production roles

### 📈 MONITORING RECOMMENDATIONS
- Add alarm for DynamoDB throttling (if usage increases)
- Monitor Lambda duration metrics (may increase with DynamoDB calls)
- Set up alarm for IAM AccessDenied errors across all Lambda functions

## Multi-Deployment Support

The module supports multiple deployments within the same AWS account and region:

```hcl
# Production deployment
module "triage_production" {
  source          = "./cloudwatch-alarm-triage"
  resource_prefix = "prod-teamA"
  sns_topic_arn   = aws_sns_topic.prod_alerts.arn
}

# Staging deployment
module "triage_staging" {
  source          = "./cloudwatch-alarm-triage"
  resource_prefix = "staging-teamA"
  sns_topic_arn   = aws_sns_topic.staging_alerts.arn
}

# Use different Lambda ARNs for different environments
resource "aws_cloudwatch_metric_alarm" "prod_errors" {
  alarm_name    = "prod-lambda-errors"
  # ... other configuration ...
  alarm_actions = [module.triage_production.triage_lambda_arn]
}
```

## Demo Project

The `demo/` directory contains a complete working example that:

1. **Creates a failing Lambda** that attempts to list EC2 instances without permissions
2. **Triggers every minute** via EventBridge rule
3. **Generates CloudWatch alarms** when errors occur
4. **Automatically investigates** using Claude and the tool Lambda
5. **Sends detailed email** with root cause analysis and remediation steps

### Running the Demo

```bash
cd demo

# Configure variables
cp terraform.tfvars.example terraform.tfvars
# Edit with your email address

# Deploy (uses us-east-2 region)
terraform init
terraform apply

# Wait 1-2 minutes for first investigation email
# Check SNS subscription confirmation in email first

# Monitor in real-time
aws logs tail "/aws/lambda/triage-demo-test-triage-handler" --region us-east-2 --follow

# Stop demo failures (alarm clears immediately)
aws events disable-rule --name "triage-demo-test-every-minute" --region us-east-2

# Cleanup when done
terraform destroy
```

See [demo/README.md](demo/README.md) and [demo/DEMO_SUMMARY.md](demo/DEMO_SUMMARY.md) for detailed documentation.

## Testing

This module includes comprehensive testing with **138 unit tests** covering:

- Lambda function handlers and error scenarios
- Bedrock client interactions and agent mode
- Tool Lambda command execution (CLI and Python)
- IAM permission validation
- SNS notification formatting
- Alarm event processing
- Security controls and access restrictions

### Run Tests

```bash
# Install dependencies
pip install -r tests/requirements.txt

# Run all tests
cd tests && python -m pytest -v

# Run with coverage
python -m pytest --cov=../lambda --cov=../tool-lambda --cov-report=html
```

## Region Support

Claude Opus 4.1 is available in select AWS regions. The module will deploy in whatever region your Terraform AWS provider is configured for. If Claude Opus 4.1 is not available in your chosen region, the module deployment will fail with a clear error message.

**Confirmed working regions:**
- us-east-2 (Ohio) - Used in demo project
- Additional regions as AWS Bedrock expands availability

## Cost Considerations

### Typical costs for moderate usage:
- **Lambda executions**: ~$1-5/month (orchestrator + tool invocations)
- **Bedrock API calls**: ~$10-50/month (varies by investigation depth and frequency)
- **CloudWatch Logs**: ~$1-3/month
- **SNS notifications**: ~$0.50/month

### Cost controls:
- Configurable `max_tokens_per_investigation` (default: 20,000)
- Tool Lambda timeout limits (default: 60 seconds)
- Optional tool Lambda concurrency limits
- Investigation depth controls (basic/detailed/comprehensive)

## Security

### Data Protection
- No sensitive data storage or logging
- CloudWatch Logs retention: 7 days (configurable)
- No access to S3 object content, DynamoDB data, or secrets
- SNS messages contain only investigation summaries (no raw data)

### Access Control
- **Orchestrator Lambda**: Minimal permissions (Bedrock, SNS, tool invocation)
- **Tool Lambda**: AWS managed ReadOnlyAccess with explicit deny statements
- Resource-based policies restrict invocation sources
- CloudTrail logging for audit trail

### Compliance
- GDPR-compliant (no PII processing)
- SOC 2 compatible design
- Audit trail via CloudWatch Logs and CloudTrail

## Troubleshooting

### Common Issues

1. **Module fails to deploy with Bedrock model error**
   - Claude Opus 4.1 not available in your region
   - Solution: Deploy in us-east-2 or another supported region

2. **Alarm doesn't trigger triage Lambda**
   - Check CloudWatch alarm configuration includes `module.triage.triage_lambda_arn`
   - Verify Lambda resource policy allows CloudWatch invocation
   - Check alarm state: `aws cloudwatch describe-alarms --alarm-names "your-alarm"`

3. **No email notifications received**
   - Confirm SNS subscription (check spam folder for confirmation)
   - Verify SNS topic ARN is correct in module configuration
   - Check orchestrator Lambda logs for SNS publish errors

4. **Tool Lambda timing out**
   - Increase `tool_lambda_timeout` (default: 60 seconds)
   - Check specific AWS CLI commands in tool Lambda logs
   - Some operations (large log queries) may need more time

5. **Investigation seems incomplete**
   - Increase `max_tokens_per_investigation` (default: 20,000)
   - Change `investigation_depth` to "comprehensive"
   - Check tool Lambda logs for command execution errors

### Debug Commands

```bash
# Check alarm state
aws cloudwatch describe-alarms --alarm-names "your-alarm-name"

# View investigation logs
aws logs tail "/aws/lambda/prefix-triage-handler" --follow

# Check tool Lambda execution
aws logs filter-log-events --log-group-name "/aws/lambda/prefix-tool-lambda" --start-time $(date -d '1 hour ago' +%s)000

# Test manual invocation
aws lambda invoke --function-name "prefix-triage-handler" --payload '{"test": true}' response.json

# Verify SNS topic subscriptions
aws sns list-subscriptions-by-topic --topic-arn "your-sns-topic-arn"
```

## Contributing

1. **Fork the repository** and create a feature branch
2. **Write tests** for new functionality (maintain >90% coverage)
3. **Run the test suite**: `cd tests && pytest -v`
4. **Test with demo project**: `cd demo && terraform apply`
5. **Submit pull request** with description of changes

### Development Setup

```bash
# Clone repository
git clone <repository-url>
cd cloudwatch-alarm-triage

# Install test dependencies
pip install -r tests/requirements.txt

# Run tests
cd tests && pytest -v --cov=../lambda --cov=../tool-lambda

# Test demo deployment
cd ../demo
terraform init
terraform plan
```

## Future Enhancements

### Phase 2
- Slack/Teams integration for notifications
- Custom investigation plugins and templates
- Historical pattern analysis and trending
- Automated remediation actions with approval workflows

### Phase 3
- Multi-region alarm correlation
- Cross-account investigation capabilities
- ML-based anomaly detection integration
- Cost anomaly investigation and optimization

### Phase 4
- Interactive chat-based investigation interface
- Runbook automation and execution
- Change correlation system with deployment tracking
- Predictive alerting based on historical patterns

## License

See the LICENSE file.

## Author

Created by [Wayne Workman](https://github.com/wayneworkman)

[![GitHub](https://img.shields.io/badge/GitHub-wayneworkman-181717?logo=github)](https://github.com/wayneworkman)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Wayne_Workman-0077B5?logo=linkedin)](https://www.linkedin.com/in/wayne-workman-a8b37b353/)

---

*This module leverages AWS Bedrock's Claude Opus 4.1 in agent mode to provide intelligent, automated alarm investigation. By combining AWS's comprehensive monitoring capabilities with Claude's analytical power, it transforms reactive alerting into proactive incident management.*