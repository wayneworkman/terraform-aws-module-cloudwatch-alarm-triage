# Demo Project Summary

## What the Demo Creates

### 1. **Failing Lambda Function**
- **Name**: `triage-demo-test-ec2-lister`
- **Purpose**: Attempts to list EC2 instances but lacks necessary permissions
- **Runtime**: Python 3.13, 128MB memory, 10-second timeout
- **IAM Role**: Only has basic Lambda execution permissions (no EC2 access)
- **Trigger**: EventBridge rule runs every minute
- **Expected Behavior**: 100% failure rate due to AccessDeniedException

### 2. **CloudWatch Alarms**
- **Primary Alarm**: `triage-demo-test-lambda-errors`
  - Triggers on any error (threshold > 0)
  - Single evaluation period (rapid detection/recovery)
  - Invokes triage Lambda on ALARM and OK states
- **Secondary Alarm**: `triage-demo-test-lambda-error-rate`
  - Triggers when error rate exceeds 50%
  - Uses metric math to calculate percentage

### 3. **Triage Infrastructure**
- **Orchestrator Lambda**: Processes alarm events, invokes Claude
- **Tool Lambda**: Executes AWS CLI commands and Python scripts for Claude
- **SNS Topic**: Sends investigation results via email
- **All necessary IAM roles and permissions**

### 4. **EventBridge Integration**
- **Rule**: `triage-demo-test-every-minute`
- **Schedule**: `rate(1 minute)` - triggers failing Lambda continuously
- **State**: Can be enabled/disabled for testing alarm recovery

## Demo Flow

```
EventBridge (every minute)
    ↓
Failing Lambda (ec2-lister)
    ↓ (fails due to missing permissions)
CloudWatch Alarm (lambda-errors)
    ↓ (triggers on first error)
Triage Orchestrator Lambda
    ↓
AI Model (Nova Premier or Claude)
    ↓ (uses tool Lambda multiple times)
Tool Lambda (executes investigation commands)
    ↓ (returns findings to AI model)
AI Analysis & Root Cause
    ↓
SNS Email Notification
```

## Expected Investigation Timeline

1. **T+0**: Demo deployment complete, EventBridge starts triggering Lambda
2. **T+1 minute**: First Lambda failure generates error metric
3. **T+1 minute**: CloudWatch alarm enters ALARM state, invokes triage Lambda
4. **T+1-2 minutes**: Triage Lambda invokes AI model with alarm event
5. **T+2-3 minutes**: AI model investigates using tool Lambda:
   - Checks CloudWatch Logs for error patterns
   - Retrieves Lambda configuration and IAM role
   - Analyzes attached IAM policies
   - Checks CloudTrail for permission denials
6. **T+3-4 minutes**: AI model synthesizes findings and provides detailed analysis
7. **T+4-5 minutes**: Investigation results sent via SNS email

## Expected Email Content

The investigation email will include:

### Executive Summary
"Lambda function is experiencing 100% error rate due to missing EC2 permissions. Immediate action required: Add ec2:DescribeInstances permission to Lambda role."

### Investigation Details
- Commands executed by AI model via tool Lambda
- Log excerpts showing AccessDeniedException
- IAM role configuration analysis
- CloudTrail events for permission denials

### Root Cause Analysis
- Missing `ec2:DescribeInstances` permission
- Lambda role only has AWSLambdaBasicExecutionRole
- No EC2-related permissions attached

### Immediate Actions
- Specific IAM policy JSON to attach
- AWS CLI commands for remediation
- Console steps for manual fix

### Prevention Recommendations
- Pre-deployment permission validation
- Integration testing for required permissions
- IAM policy review process

## Testing Scenarios

### Scenario 1: Initial Investigation
- Deploy demo → Wait 1-2 minutes → Verify alarm triggers → Check email
- **Success Criteria**: Detailed investigation email received within 5 minutes

### Scenario 2: Rapid Alarm Recovery
- Disable EventBridge rule → Wait 1 minute → Verify alarm clears
- **Success Criteria**: Alarm returns to OK state within 1 minute

### Scenario 3: Re-triggering
- Re-enable EventBridge rule → Wait 1 minute → Verify alarm triggers again
- **Success Criteria**: New investigation triggered within 1 minute

### Scenario 4: Investigation Quality
Review email for:
- ✅ Specific error identification (AccessDeniedException)
- ✅ IAM policy analysis (missing permissions identified)
- ✅ Actionable remediation steps
- ✅ Preventive recommendations
- ✅ Tool execution audit trail

## Monitoring Commands

### Real-time Monitoring
```bash
# Watch alarm state
watch -n 5 'aws cloudwatch describe-alarms --alarm-names "triage-demo-test-lambda-errors" --region us-east-2 --query "MetricAlarms[0].StateValue" --output text'

# Monitor all Lambda logs
aws logs tail "/aws/lambda/triage-demo-test-triage-handler" --region us-east-2 --follow &
aws logs tail "/aws/lambda/triage-demo-test-tool-lambda" --region us-east-2 --follow &
aws logs tail "/aws/lambda/triage-demo-test-ec2-lister" --region us-east-2 --follow &
```

### Control Commands
```bash
# Stop demo failures (alarm will clear)
aws events disable-rule --name "triage-demo-test-every-minute" --region us-east-2

# Restart failures (alarm will trigger)
aws events enable-rule --name "triage-demo-test-every-minute" --region us-east-2

# Manual investigation trigger
aws lambda invoke \
  --function-name "triage-demo-test-triage-handler" \
  --region us-east-2 \
  --payload '{"source":"manual-test","alarmData":{"alarmName":"Manual Test","state":{"value":"ALARM"}}}' \
  response.json
```

## Architecture Validation

The demo validates:
- ✅ Module deploys successfully in us-east-2
- ✅ Triage Lambda can be invoked by CloudWatch Alarms
- ✅ Tool Lambda can be invoked by orchestrator Lambda
- ✅ AI model (Nova Premier/Claude) works with tool access
- ✅ Investigation commands execute successfully
- ✅ SNS notifications are properly formatted
- ✅ All IAM permissions are correctly configured
- ✅ Alarm state transitions work as expected
- ✅ Multiple tool invocations within single investigation
- ✅ Real AWS API calls provide accurate data for analysis

## Cost Breakdown

**Daily costs while demo runs:**
- Lambda executions: ~$0.01 (failing Lambda + triage invocations)
- Bedrock API: ~$0.10-2.00 per investigation (Nova Premier is more cost-effective)
- CloudWatch: ~$0.01 (logs, metrics, alarms)
- SNS: ~$0.01 (email notifications)

**Total**: $1-3 per day of continuous operation

## Cleanup Instructions

```bash
# Stop failures (optional - reduces final costs)
aws events disable-rule --name "triage-demo-test-every-minute" --region us-east-2

# Destroy all resources
terraform destroy

# Verify cleanup
aws lambda list-functions --region us-east-2 --query "Functions[?contains(FunctionName, 'triage-demo-test')]"
aws cloudwatch describe-alarms --region us-east-2 --alarm-name-prefix "triage-demo-test"
```

The demo provides a complete, realistic scenario that validates the entire CloudWatch Alarm Triage system from end to end.