# CloudWatch Alarm Triage with AWS Bedrock

Created by [Wayne Workman](https://github.com/wayneworkman)

[![Blog](https://img.shields.io/badge/Blog-wayne.theworkmans.us-blue)](https://wayne.theworkmans.us/)
[![GitHub](https://img.shields.io/badge/GitHub-wayneworkman-181717?logo=github)](https://github.com/wayneworkman)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Wayne_Workman-0077B5?logo=linkedin)](https://www.linkedin.com/in/wayne-workman-a8b37b353/)

## Overview

A reusable Terraform module that integrates AWS CloudWatch Alarms with AWS Bedrock models in agent mode to automatically investigate and triage alarms. The AI model operates as an agent with access to a Python execution tool that can run boto3 operations and analysis code with pre-imported libraries, providing deep investigation capabilities. This solution provides engineers with comprehensive contextual information and preliminary analysis before they respond to incidents, significantly reducing mean time to resolution (MTTR).

**Supported Models**: 
- Default: Amazon Nova Premier (`us.amazon.nova-premier-v1:0`) - Cost-effective option
- Claude Opus 4.1: `anthropic.claude-opus-4-1-20250805-v1:0` - Maximum capability
- Module uses the region of your calling Terraform provider
- Models must be available in your deployment region

## Key Features

- **System Inference Profile**: Uses AWS-managed inference profile for reliable model invocation
- **Robust Error Handling**: Automatic retries with exponential backoff for API timeouts
- **5-Minute Read Timeout**: Extended timeout for handling complex investigations
- **100 Tool Call Iterations**: Supports thorough multi-step investigations
- **DynamoDB Deduplication**: Prevents duplicate investigations with configurable time window
- **Pre-imported Python Modules**: Fast execution with 40+ pre-imported Python libraries
- **Concurrent Execution Control**: Prevents overlapping investigations
- **Cost Optimization**: Automatic import statement removal enables use of more economical AI models

## Architecture

### Two-Lambda Design

This module creates **two Lambda functions** working together:

1. **Orchestrator Lambda** (Python 3.13)
   - Receives CloudWatch Alarm events
   - Invokes Bedrock model in agent mode
   - Sends investigation results to SNS
   - Minimal IAM permissions (Bedrock, SNS, Logs)

2. **Tool Lambda** (Python 3.13)
   - Called by the AI model as a tool during investigation
   - Executes Python code with pre-imported modules
   - Uses AWS managed `ReadOnlyAccess` policy with deny statements
   - Prevents access to sensitive data (S3 objects, DynamoDB data, secrets)
   - All standard library and AWS SDK modules pre-imported for performance

### Workflow

```
CloudWatch Alarm (ALARM state)
    ↓
Orchestrator Lambda
    ↓
DynamoDB Deduplication Check
    ↓ (if not recently investigated)
Bedrock Model (agent mode)
    ↓ (multiple tool calls)
Tool Lambda (Python executor)
    ↓ (returns findings)
AI Analysis & Root Cause
    ↓
Save Report to S3 Bucket
    ↓
SNS Email Notification
```

### Deduplication

The module uses DynamoDB to prevent duplicate investigations of the same alarm within a configurable time window (default: 1 hour). This prevents multiple emails when CloudWatch continuously evaluates an alarm in ALARM state. The DynamoDB entries automatically expire using TTL.

### Investigation Reports Storage

All investigation reports are automatically saved to an S3 bucket with the following features:
- **Encryption**: Server-side encryption with AES256
- **Versioning**: Enabled for audit trail
- **Access Control**: Public access blocked with bucket ACLs
- **Organization**: Reports organized by date (`reports/YYYY/MM/DD/`)
- **Optional Logging**: Configure access logging to track report access
- **Optional Lifecycle**: Auto-delete old reports after specified days
- **Naming Convention**: `{prefix}-alarm-reports-{random}` for uniqueness

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
│   ├── prompt_template.py  # AI prompt template
│   └── requirements.txt    # Python dependencies
├── tool-lambda/
│   └── tool_handler.py     # Python executor handler
├── tests/
│   ├── unit/               # Unit tests (204 tests)
│   ├── integration/        # Integration tests (7 tests)
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
# Configure provider for region with Bedrock models
provider "aws" {
  region = "us-east-2"  # Ensure Bedrock models are available in your region
}

# Create SNS topic for notifications
resource "aws_sns_topic" "alarm_notifications" {
  name = "cloudwatch-alarm-investigations"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarm_notifications.arn
  protocol  = "email"
  endpoint  = "your-email@example.com"
}

# Deploy the triage module
module "alarm_triage" {
  source = "github.com/wayneworkman/terraform-aws-module-cloudwatch-alarm-triage"
  
  sns_topic_arn = aws_sns_topic.alarm_notifications.arn
  
  # Optional: Override the default model (Nova Premier)
  # bedrock_model_id = "anthropic.claude-opus-4-1-20250805-v1:0"  # For maximum capability
  
  tags = {
    Environment = "production"
    ManagedBy   = "terraform"
  }
}
```

### 2. Configure CloudWatch Alarms

Add the triage Lambda as an action on your CloudWatch alarms:

```hcl
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "lambda-high-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "60"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "Triggers when Lambda errors exceed threshold"
  
  dimensions = {
    FunctionName = aws_lambda_function.my_function.function_name
  }
  
  # Add triage Lambda as alarm action
  alarm_actions = [
    module.alarm_triage.triage_lambda_arn
  ]
}
```

### 3. Confirm Email Subscription

Check your email and confirm the SNS subscription to receive investigation results.

## Module Inputs

| Variable | Description | Type | Default |
|----------|-------------|------|---------|
| `sns_topic_arn` | SNS topic ARN for sending investigation results | `string` | Required |
| `bedrock_model_id` | Bedrock model identifier | `string` | `"us.amazon.nova-premier-v1:0"` |
| `lambda_timeout` | Timeout for orchestrator Lambda in seconds | `number` | `900` |
| `lambda_memory_size` | Memory for orchestrator Lambda in MB | `number` | `1024` |
| `tool_lambda_timeout` | Timeout for tool Lambda in seconds | `number` | `60` |
| `tool_lambda_memory_size` | Memory for tool Lambda in MB | `number` | `2048` |
| `tool_lambda_reserved_concurrency` | Reserved concurrent executions for tool Lambda | `number` | `-1` (unreserved) |
| `investigation_window_hours` | Hours before re-investigating same alarm | `number` | `1` |
| `resource_prefix` | Prefix for all created resources | `string` | `""` |
| `resource_suffix` | Suffix for all created resources | `string` | `""` |
| `tags` | Tags to apply to all resources | `map(string)` | `{}` |

## Module Outputs

| Output | Description |
|--------|-------------|
| `triage_lambda_arn` | ARN of the triage Lambda function |
| `triage_lambda_name` | Name of the triage Lambda function |
| `tool_lambda_arn` | ARN of the tool Lambda function |
| `tool_lambda_name` | Name of the tool Lambda function |
| `triage_lambda_log_group` | CloudWatch Logs group for the triage Lambda |
| `tool_lambda_log_group` | CloudWatch Logs group for the tool Lambda |
| `bedrock_model_id` | The Bedrock model ID being used |
| `dynamodb_table_name` | Name of the DynamoDB table for deduplication |

## Investigation Capabilities

The AI model can investigate alarms by executing Python code with pre-imported modules:

### Intelligent Import Statement Handling

The tool Lambda includes intelligent import statement removal to maximize compatibility with various AI models. When more economical models inadvertently include import statements despite instructions, the system automatically:

1. **Detects and removes** all import statements from the provided code
2. **Logs the removed imports** for transparency
3. **Continues execution** with the pre-imported modules

This approach ensures reliable execution across different model tiers, enabling cost optimization without sacrificing functionality. The feature transparently handles common patterns where AI models might generate code like:

```python
import boto3
from datetime import datetime
import json

# Your investigation code here...
```

The system automatically strips these imports and executes the code successfully, as all required modules are already pre-imported in the execution environment.

### Pre-Imported Modules Available

#### Core AWS & Data
- **boto3** - AWS SDK for all AWS operations
- **json** - JSON encoding/decoding
- **csv** - CSV file operations
- **base64** - Base64 encoding/decoding

#### Date & Time
- **datetime** - The datetime class from datetime module
- **timedelta** - Direct access to datetime.timedelta class
- **time** - Time-related functions

#### Text & Pattern Matching
- **re** - Regular expressions
- **string** - String constants and utilities
- **textwrap** - Text wrapping and filling
- **difflib** - Helpers for computing differences
- **fnmatch** - Unix-style pattern matching
- **glob** - Unix-style pathname pattern expansion

#### Data Structures & Algorithms
- **collections** - Counter, defaultdict, OrderedDict, etc.
- **itertools** - Functions for creating iterators
- **functools** - Higher-order functions
- **operator** - Standard operators as functions
- **copy** - Shallow and deep copy operations

#### Network & Security
- **ipaddress** - IP network/address manipulation
- **hashlib** - Secure hash algorithms
- **urllib** - URL handling modules
- **uuid** - UUID generation

#### Math & Statistics
- **math** - Mathematical functions
- **statistics** - Statistical functions
- **random** - Random number generation
- **decimal** - Decimal arithmetic
- **fractions** - Rational number arithmetic

#### System & Utility
- **os** - Operating system interface (limited in Lambda)
- **sys** - System-specific parameters
- **platform** - Platform identification
- **traceback** - Traceback utilities
- **warnings** - Warning control
- **pprint** - Pretty printer

#### Type Hints & Data Classes
- **enum** - Support for enumerations
- **dataclasses** - Data class support
- **typing** - Type hints support

#### I/O Operations
- **StringIO** - In-memory text streams
- **BytesIO** - In-memory byte streams

#### Compression
- **gzip** - Gzip compression
- **zlib** - Compression library
- **tarfile** - Tar archive access
- **zipfile** - ZIP archive access

### Investigation Examples
- **CloudWatch Logs Analysis** - Filter and analyze application logs
- **Metric Statistics** - Review trends and anomalies
- **IAM Permissions** - Check roles and policies
- **CloudTrail Events** - Find recent API calls
- **EC2 Instances** - Examine infrastructure state
- **Lambda Functions** - Review configurations and errors
- **Complex Analysis** - Pattern detection, cost optimization, multi-resource correlation

### Security Model

The tool Lambda uses:
- **AWS managed ReadOnlyAccess policy** for comprehensive resource inspection
- **Explicit deny statements** for sensitive data:
  - S3 object content (can list, cannot read)
  - DynamoDB data (can describe, cannot query)
  - Secrets Manager values (can list, cannot retrieve)
  - Parameter Store SecureString parameters (can list, cannot decrypt)

## Example Investigation Output

When a Lambda function alarm triggers, the AI model might provide:

### 🚨 EXECUTIVE SUMMARY
Lambda function `prod-api-handler` experiencing 100% error rate due to missing DynamoDB table permissions. Immediate action required: Add `dynamodb:GetItem` permission to Lambda role.

### 🔍 INVESTIGATION DETAILS
**Python code executed:**
1. CloudWatch Logs analysis:
   ```python
   logs = boto3.client('logs')
   response = logs.filter_log_events(
       logGroupName='/aws/lambda/prod-api-handler',
       startTime=int((datetime.now() - timedelta(minutes=5)).timestamp() * 1000)
   )
   ```
   - Found 47 AccessDenied errors in past 5 minutes
   - All errors: "User: arn:aws:sts::123456789012:assumed-role/lambda-role/prod-api-handler is not authorized to perform: dynamodb:GetItem on resource: arn:aws:dynamodb:us-east-2:123456789012:table/UserData"

2. IAM role policy check:
   ```python
   iam = boto3.client('iam')
   policies = iam.list_attached_role_policies(RoleName='lambda-role')
   ```
   - Only AWSLambdaBasicExecutionRole attached
   - No DynamoDB permissions found

3. DynamoDB table verification:
   ```python
   dynamodb = boto3.client('dynamodb')
   table = dynamodb.describe_table(TableName='UserData')
   ```
   - Table exists and is ACTIVE
   - No resource-level restrictions

### 📊 ROOT CAUSE
Lambda role lacks `dynamodb:GetItem` permission for the UserData table. This occurred after the recent IAM policy update that removed the overly permissive `*` resource access.

### 💥 IMPACT ASSESSMENT
- **Affected Resources**: prod-api-handler Lambda function
- **Business Impact**: API completely unavailable, all requests failing
- **Severity Level**: Critical
- **Users Affected**: All users (estimated 5,000+ active)

### 🔧 IMMEDIATE ACTIONS
1. Add DynamoDB permissions to Lambda role:
   ```bash
   aws iam attach-role-policy \
     --role-name lambda-role \
     --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess
   ```
   **Time estimate**: 2 minutes

2. Verify function recovery:
   - Monitor CloudWatch metrics for error rate drop
   - Test API endpoints manually
   **Time estimate**: 5 minutes

### 🛡️ PREVENTION MEASURES
- Implement least-privilege IAM policies with explicit resource ARNs
- Add pre-deployment IAM policy validation
- Create Lambda function tests that verify DynamoDB access

### 📈 MONITORING RECOMMENDATIONS
- Set alarm threshold to 5 errors (current: 10)
- Add custom metric for DynamoDB throttling
- Create dashboard showing Lambda errors by error type

## Advanced Configuration

### Resource Naming

Control resource names with prefixes and suffixes:

```hcl
module "alarm_triage" {
  source = "github.com/wayneworkman/terraform-aws-module-cloudwatch-alarm-triage"
  
  resource_prefix = "prod"
  resource_suffix = "us-east-2"
  # Creates: prod-triage-handler-us-east-2
  
  sns_topic_arn = aws_sns_topic.alarms.arn
}
```

### Lambda Configuration

Adjust Lambda resources based on your needs (defaults shown):

```hcl
module "alarm_triage" {
  source = "github.com/wayneworkman/terraform-aws-module-cloudwatch-alarm-triage"
  
  # Orchestrator Lambda configuration
  lambda_timeout      = 900  # Default: 15 minutes (hard-coded maximum)
  lambda_memory_size  = 512  # Default: 512 MB
  
  # Tool Lambda configuration  
  tool_lambda_timeout              = 120  # Default: 2 minutes
  tool_lambda_memory_size          = 512  # Default: 512 MB
  tool_lambda_reserved_concurrency = -1   # Default: no limit
  
  sns_topic_arn = aws_sns_topic.alarms.arn
}
```

### Deduplication Window

Control how often the same alarm is investigated:

```hcl
module "alarm_triage" {
  source = "github.com/wayneworkman/terraform-aws-module-cloudwatch-alarm-triage"
  
  investigation_window_hours = 4  # Only investigate same alarm every 4 hours
  
  sns_topic_arn = aws_sns_topic.alarms.arn
}
```

### S3 Reports Configuration

Configure the S3 bucket for storing investigation reports:

```hcl
module "alarm_triage" {
  source = "github.com/wayneworkman/terraform-aws-module-cloudwatch-alarm-triage"
  
  # Optional: Configure S3 access logging
  reports_bucket_logging = {
    target_bucket = "my-logging-bucket"
    target_prefix = "alarm-reports/"
  }
  
  # Optional: Auto-delete old reports after 90 days
  reports_bucket_lifecycle_days = 90
  
  sns_topic_arn = aws_sns_topic.alarms.arn
}
```

## Security Considerations

### IAM Permissions
- Tool Lambda has read-only access to most AWS services
- Explicit deny policies prevent access to sensitive data
- No ability to modify resources or access secrets

### Data Protection
- No customer data is stored beyond the investigation window
- DynamoDB entries auto-expire via TTL
- All logs respect CloudWatch retention policies

### Network Security
- Lambdas run in AWS-managed VPC by default
- Can be configured for VPC deployment if needed
- All AWS API calls use TLS encryption

### Compliance
- GDPR-compliant (no PII processing)
- SOC 2 compatible design
- Audit trail via CloudWatch Logs and CloudTrail

## Troubleshooting

### Common Issues

1. **Module fails to deploy with Bedrock model error**
   - Bedrock models not available in your region
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
   - Check specific Python code execution in tool Lambda logs
   - Some operations (large log queries, pagination) may need more time

5. **Investigation seems incomplete**
   - Consider using a more capable model like Claude Opus
   - Check if tool Lambda is hitting memory limits
   - Increase lambda_timeout if investigations are timing out

6. **Duplicate investigations occurring**
   - Check `investigation_window_hours` setting
   - Verify DynamoDB table TTL is enabled
   - Look for multiple alarm evaluations in CloudWatch

### Viewing Logs

Check CloudWatch Logs for debugging:

```bash
# Orchestrator Lambda logs
aws logs tail /aws/lambda/triage-handler --follow

# Tool Lambda logs  
aws logs tail /aws/lambda/tool-lambda --follow

# Filter for specific alarm
aws logs filter-log-events \
  --log-group-name /aws/lambda/triage-handler \
  --filter-pattern "alarm-name"
```

### Testing

Test the module with a manual alarm trigger:

```bash
# Manually put an alarm into ALARM state
aws cloudwatch set-alarm-state \
  --alarm-name "test-alarm" \
  --state-value ALARM \
  --state-reason "Manual test"
```

## Cost Optimization

### Estimated Costs

Based on typical usage (100 alarms/month with default 512MB Lambda memory):
- **Bedrock**: ~$3-10/month (depends on investigation complexity)
- **Lambda**: <$1/month (optimized with 512MB default memory)
- **DynamoDB**: <$1/month
- **CloudWatch Logs**: <$1/month
- **S3**: <$1/month (for report storage)
- **SNS**: <$1/month

### Cost Reduction Tips

1. **Use cost-effective models** - Nova Premier is the default for cost optimization
2. **Increase deduplication window** - Reduce duplicate investigations
3. **Use reserved concurrency** - Prevent runaway Lambda costs
4. **Configure log retention** - Reduce CloudWatch Logs storage
5. **Optimize Lambda memory** - Adjust based on actual usage

## Testing

The module includes comprehensive test coverage with **223 tests** achieving **96% code coverage**:

```bash
# Run all tests
python -m pytest tests/ -v

# Run unit tests only (216 tests)
python -m pytest tests/unit/ -v

# Run integration tests only (7 tests)
python -m pytest tests/integration/ -v

# Run with coverage report
python -m pytest tests/ --cov=lambda --cov=tool-lambda --cov-report=term-missing
```

### Test Categories
- **Deduplication & Formatting**: DynamoDB deduplication logic, notification formatting
- **Malformed Events**: Edge cases, null values, invalid configurations
- **Performance & Load**: Concurrency, memory/CPU stress, high-volume operations
- **Security Boundaries**: IAM permissions, credential protection, injection prevention
- **Integration**: End-to-end alarm investigation workflow

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues or questions:
- Open an issue on [GitHub](https://github.com/wayneworkman/terraform-aws-module-cloudwatch-alarm-triage)
- Contact via [LinkedIn](https://www.linkedin.com/in/wayne-workman-a8b37b353/)

## Acknowledgments

- Compatible with multiple AWS Bedrock models including Claude and Nova
- Powered by AWS Bedrock
- Terraform module best practices from HashiCorp