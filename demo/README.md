# CloudWatch Alarm Triage Demo

Part of the [CloudWatch Alarm Triage](../) project by [Wayne Workman](https://github.com/wayneworkman)

## Overview

This demo showcases the CloudWatch Alarm Triage module's capabilities through a controlled failure scenario. It creates an intentionally failing Lambda function that demonstrates how Claude Opus 4.1 can automatically investigate and diagnose AWS infrastructure issues.

## Demo Scenario: Lambda Permission Failure

The demo creates a realistic production failure:

1. **Failing Lambda** - Attempts to list EC2 instances but lacks necessary IAM permissions
2. **EventBridge Rule** - Triggers the Lambda every minute, generating consistent errors
3. **CloudWatch Alarm** - Detects Lambda errors and triggers the triage system
4. **Automatic Investigation** - Claude investigates using the tool Lambda and provides detailed analysis

## Region Configuration

This demo is configured to run in **us-east-2** where Claude Opus 4.1 is available. The AWS provider is configured in `main.tf` with `region = "us-east-2"`.

## Prerequisites

- AWS CLI configured with admin permissions
- Terraform >= 1.5.0 installed
- Valid email address for notifications
- AWS account with Bedrock access in us-east-2

## Quick Start

1. **Configure the demo**:
   ```bash
   cd demo
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your email address
   ```

2. **Deploy the demo**:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

3. **Monitor the investigation**:
   ```bash
   # Check if the alarm has triggered (should happen within 1-2 minutes)
   aws cloudwatch describe-alarms \
     --alarm-names "$(terraform output -raw demo_alarm_name)" \
     --region us-east-2 \
     --query "MetricAlarms[0].StateValue"

   # Watch the triage Lambda logs in real-time
   aws logs tail "$(terraform output -raw triage_lambda_log_group)" \
     --region us-east-2 --follow
   ```

4. **Check your email** for Claude's detailed investigation report

5. **Test alarm recovery**:
   ```bash
   # Stop the failures (alarm should clear in ~1 minute)
   aws events disable-rule \
     --name "$(terraform output -raw demo_failing_lambda_name | sed 's/ec2-lister/every-minute/')" \
     --region us-east-2

   # Restart failures (alarm should trigger in ~1 minute)
   aws events enable-rule \
     --name "$(terraform output -raw demo_failing_lambda_name | sed 's/ec2-lister/every-minute/')" \
     --region us-east-2
   ```

## Expected Investigation Results

When the triage system investigates the failing Lambda, Claude will:

### 1. **Gather Context**
- Filter CloudWatch Logs for error patterns
- Retrieve Lambda configuration and IAM role
- Check recent CloudTrail events for permission denials
- Analyze IAM policies attached to the Lambda role

### 2. **Root Cause Analysis**
Claude will identify:
- AccessDeniedException when calling DescribeInstances
- Lambda role only has AWSLambdaBasicExecutionRole
- Missing `ec2:DescribeInstances` permission

### 3. **Provide Actionable Remediation**
The investigation will include:
- Specific IAM policy needed to fix the issue
- Step-by-step AWS CLI commands for resolution
- Prevention recommendations for future deployments

### Example Investigation Output
```
🚨 EXECUTIVE SUMMARY
Lambda function is experiencing 100% error rate due to missing EC2 permissions. 
Immediate action required: Add ec2:DescribeInstances permission to Lambda role.

🔍 INVESTIGATION DETAILS
Commands executed:
1. aws logs filter-log-events --log-group-name /aws/lambda/triage-demo-ec2-lister
   → Found consistent AccessDeniedException errors
2. aws lambda get-function --function-name triage-demo-ec2-lister
   → Retrieved Lambda configuration and IAM role ARN
3. aws iam list-attached-role-policies --role-name triage-demo-restricted-lambda-role
   → Only AWSLambdaBasicExecutionRole attached - no EC2 permissions

📊 ROOT CAUSE
The Lambda execution role lacks ec2:DescribeInstances permission required by the function.

🔧 IMMEDIATE ACTIONS
1. Create IAM policy with EC2 read permissions
2. Attach policy to Lambda role: triage-demo-restricted-lambda-role
3. Test Lambda function execution

🛡️ PREVENTION MEASURES
- Implement IAM policy validation in CI/CD pipeline
- Add integration tests that verify required permissions
```

## Architecture Details

### Demo Components

1. **Failing Lambda** (`demo/lambda_code/failing_lambda.py`)
   - Attempts `ec2.describe_instances()` every minute
   - IAM role has only basic Lambda execution permissions
   - Logs detailed context for Claude's investigation

2. **EventBridge Rule**
   - Triggers Lambda every minute on `rate(1 minute)` schedule
   - Can be enabled/disabled for testing
   - Includes retry policy for reliability

3. **CloudWatch Alarms**
   - **Lambda Errors**: Triggers on any error (threshold > 0)
   - **Error Rate**: Triggers when error rate exceeds 50%
   - Both use single evaluation period for rapid detection/recovery

4. **Triage Integration**
   - Alarms automatically invoke the triage Lambda
   - Investigation results sent via SNS email
   - Complete audit trail in CloudWatch Logs

### Resource Naming

All demo resources use the configurable prefix (default: `triage-demo`):
- Lambda: `triage-demo-ec2-lister`
- Alarms: `triage-demo-lambda-errors`, `triage-demo-lambda-error-rate`
- IAM Role: `triage-demo-restricted-lambda-role`
- EventBridge Rule: `triage-demo-every-minute`

## Monitoring Commands

### Real-time Monitoring
```bash
# Watch alarm state changes
watch -n 5 'aws cloudwatch describe-alarms \
  --alarm-names "triage-demo-lambda-errors" \
  --region us-east-2 \
  --query "MetricAlarms[0].StateValue" --output text'

# Monitor all Lambda logs simultaneously
aws logs tail "/aws/lambda/triage-demo-triage-handler" --region us-east-2 --follow &
aws logs tail "/aws/lambda/triage-demo-tool-lambda" --region us-east-2 --follow &
aws logs tail "/aws/lambda/triage-demo-ec2-lister" --region us-east-2 --follow &
```

### Historical Analysis
```bash
# View recent alarm history
aws cloudwatch describe-alarm-history \
  --alarm-name "triage-demo-lambda-errors" \
  --region us-east-2 \
  --max-items 10

# Check Lambda error metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=triage-demo-ec2-lister \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum \
  --region us-east-2
```

## Testing Scenarios

### 1. **Initial Deployment Test**
- Deploy demo → Wait 1-2 minutes → Verify alarm triggers → Check email
- **Expected**: Alarm ALARM state, detailed investigation email received

### 2. **Rapid Recovery Test**
- Disable EventBridge rule → Wait 1 minute → Verify alarm clears
- **Expected**: Alarm OK state within 1 minute

### 3. **Re-triggering Test**
- Re-enable EventBridge rule → Wait 1 minute → Verify alarm triggers
- **Expected**: Alarm ALARM state within 1 minute, new investigation

### 4. **Investigation Quality Test**
- Review Claude's analysis for:
  - ✅ Specific error identification (AccessDeniedException)
  - ✅ IAM role analysis (missing permissions)
  - ✅ Actionable remediation steps
  - ✅ Prevention recommendations

## Troubleshooting

### Common Issues

**Alarm not triggering after 2 minutes**:
```bash
# Check if EventBridge rule is enabled
aws events describe-rule --name "triage-demo-every-minute" --region us-east-2

# Check if Lambda is actually failing
aws logs filter-log-events \
  --log-group-name "/aws/lambda/triage-demo-ec2-lister" \
  --start-time $(date -u -d '5 minutes ago' +%s)000 \
  --region us-east-2
```

**No email received**:
```bash
# Check SNS topic subscription status
aws sns list-subscriptions-by-topic \
  --topic-arn "$(terraform output -raw sns_topic_arn)" \
  --region us-east-2

# Check triage Lambda logs for errors
aws logs filter-log-events \
  --log-group-name "$(terraform output -raw triage_lambda_log_group)" \
  --filter-pattern "ERROR" \
  --region us-east-2
```

**Bedrock access issues**:
```bash
# Test Bedrock access
aws bedrock list-foundation-models --region us-east-2

# Check if Claude Opus 4.1 is available
aws bedrock list-foundation-models \
  --region us-east-2 \
  --query "modelSummaries[?contains(modelId, 'claude-opus-4-1')]"
```

### Manual Testing

To manually trigger an investigation:
```bash
# Create a test alarm event
aws lambda invoke \
  --function-name "$(terraform output -raw triage_lambda_arn)" \
  --region us-east-2 \
  --payload '{"source":"manual-test","alarmData":{"alarmName":"Manual Test","state":{"value":"ALARM"}}}' \
  response.json

cat response.json
```

## Cleanup

```bash
# Stop the demo failures first (optional)
aws events disable-rule --name "triage-demo-every-minute" --region us-east-2

# Destroy all resources
terraform destroy

# Confirm cleanup
aws lambda list-functions --region us-east-2 --query "Functions[?contains(FunctionName, 'triage-demo')]"
```

## Cost Considerations

The demo incurs minimal costs:
- **Lambda**: ~$0.01/day (failing Lambda runs 1,440 times/day)
- **Bedrock**: ~$0.50-2.00 per investigation (depends on investigation depth)
- **CloudWatch**: ~$0.01/day for logs and metrics
- **SNS**: ~$0.01/day for notifications

**Total estimated cost**: $1-3 per day while demo is running.

## Next Steps

After validating the demo:

1. **Use the triage Lambda in production alarms**:
   ```bash
   # Get the triage Lambda ARN
   TRIAGE_ARN=$(terraform output -raw triage_lambda_arn)
   
   # Use in your CloudWatch Alarms
   aws cloudwatch put-metric-alarm \
     --alarm-name "MyProductionAlarm" \
     --alarm-actions "$TRIAGE_ARN" \
     --metric-name CPUUtilization \
     --namespace AWS/EC2 \
     --statistic Average \
     --period 300 \
     --threshold 80 \
     --comparison-operator GreaterThanThreshold \
     --evaluation-periods 2 \
     --region us-east-2
   ```

2. **Customize investigation depth**:
   - Edit `investigation_depth` in `main.tf`
   - Options: `basic`, `detailed`, `comprehensive`

3. **Deploy in other regions**:
   - Update provider region to another Claude Opus 4.1 region
   - Ensure Bedrock access is available

4. **Integrate with existing infrastructure**:
   - Reference the module from other Terraform projects
   - Add the triage Lambda ARN to existing alarms

## Support

For issues or questions:
- Check the main [project documentation](../)
- Review CloudWatch Logs for detailed error information
- Verify all prerequisites are met
- Test with manual Lambda invocation first

The demo validates that the complete triage system works end-to-end in a realistic scenario.