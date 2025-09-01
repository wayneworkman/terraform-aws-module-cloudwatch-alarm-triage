"""Tests for trailing tool call cleanup in Bedrock client responses."""

import pytest
from unittest.mock import MagicMock, patch, call
import sys
import os

# Add the lambda directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from bedrock_client import BedrockAgentClient


class TestTrailingToolCleanup:
    """Test cleanup of trailing tool calls that Nova Premier sometimes appends."""
    
    @patch('bedrock_client.boto3.client')
    def test_cleanup_trailing_tool_call_basic(self, mock_boto_client):
        """Test removal of basic trailing tool call from analysis response."""
        # Mock the Bedrock and Lambda clients
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        # Create the client with mocked boto3
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        # Simulate a response with analysis followed by trailing tool call
        analysis_with_trailing_tool = """### 🚨 EXECUTIVE SUMMARY
The CloudWatch alarm triggered due to elevated error rates in the Lambda function. Investigation shows DynamoDB throttling as the root cause.

### 🔍 INVESTIGATION DETAILS
- Error rate: 15% over last 5 minutes
- Primary error: DynamoDB throttling exceptions
- Affected function: payment-processor

### 💥 IMPACT ASSESSMENT
- Business Impact: Payment processing delays
- Users Affected: ~500 active users experiencing failures

### 🔧 IMMEDIATE ACTIONS
1. Increase DynamoDB read/write capacity units
2. Implement exponential backoff in Lambda function
3. Monitor error rates for next 30 minutes

TOOL: python_executor
```python
# Fetch additional CloudWatch metrics
print("Getting CloudWatch metrics for detailed analysis...")
cloudwatch = boto3.client('cloudwatch', region_name='us-east-2')
response = cloudwatch.get_metric_statistics(
    Namespace='AWS/Lambda',
    MetricName='Errors',
    StartTime=datetime.now() - timedelta(minutes=30),
    EndTime=datetime.now(),
    Period=300,
    Statistics=['Sum']
)
print(f"Found {len(response['Datapoints'])} error datapoints")
result = {"metrics": response['Datapoints']}
```

### Follow-up Analysis
This additional investigation will provide more context for the error patterns."""
        
        # Configure mock to return the response with trailing tool
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': analysis_with_trailing_tool}]
                }
            }
        }
        
        # Execute the investigation
        result = bedrock_client.investigate_with_tools("Investigate alarm")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify the trailing tool call was removed
        assert "TOOL: python_executor" not in report
        assert "```python" not in report
        assert "cloudwatch.get_metric_statistics" not in report
        assert "Follow-up Analysis" not in report
        
        # Verify the main content is preserved
        assert "### 🚨 EXECUTIVE SUMMARY" in report
        assert "DynamoDB throttling" in report
        assert "### 🔧 IMMEDIATE ACTIONS" in report
        assert "Implement exponential backoff" in report
    
    @patch('bedrock_client.boto3.client')
    def test_cleanup_trailing_tool_call_with_narrative(self, mock_boto_client):
        """Test removal of trailing tool call with explanatory text."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        response_with_narrative = """### 🚨 EXECUTIVE SUMMARY
API Gateway returning 502 errors due to Lambda timeout issues.

### 📊 ROOT CAUSE ANALYSIS
The Lambda function is timing out after 30 seconds when processing large payloads.

### 🔧 IMMEDIATE ACTIONS
1. Increase Lambda timeout to 60 seconds
2. Implement request size validation
3. Add CloudWatch alarm for timeout metrics

### 📝 ADDITIONAL NOTES
Monitor the function performance after applying fixes.

TOOL: python_executor
```python
# Step 1: Get recent CloudWatch Logs for the affected Lambda function
print("Fetching CloudWatch Logs for /aws/lambda/api-handler...");
logs_client = boto3.client('logs', region_name='us-east-2');

streams_response = logs_client.describe_log_streams(
    logGroupName='/aws/lambda/api-handler',
    orderBy='LastEventTime',
    descending=True,
    limit=5
);

print(f"Found {len(streams_response['logStreams'])} log streams");
result = {"log_streams": streams_response['logStreams']};
```

I'll start by analyzing the CloudWatch Logs for the api-handler Lambda function to identify timeout patterns."""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': response_with_narrative}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Investigate timeout alarm")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify cleanup
        assert "TOOL: python_executor" not in report
        assert "I'll start by analyzing" not in report
        assert "describe_log_streams" not in report
        
        # Verify preservation
        assert "502 errors" in report
        assert "### 📝 ADDITIONAL NOTES" in report
        assert "Monitor the function performance" in report
    
    @patch('bedrock_client.boto3.client')
    def test_no_cleanup_when_no_trailing_tool(self, mock_boto_client):
        """Test that responses without trailing tools are not modified."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        clean_response = """### 🚨 EXECUTIVE SUMMARY
Database connection pool exhausted causing application errors.

### 🔍 INVESTIGATION DETAILS
- Current connections: 100/100 (maxed out)
- Average query time: 2.5 seconds
- Connection timeout errors: 47 in last hour

### 💥 IMPACT ASSESSMENT
- Service availability: 60% degraded
- Response times: 10x normal latency

### 🔧 IMMEDIATE ACTIONS
1. Increase connection pool size to 200
2. Investigate slow queries causing connection holding
3. Implement connection pooling best practices

### 🛡️ PREVENTION MEASURES
- Add monitoring for connection pool utilization
- Implement query timeout limits
- Set up auto-scaling for read replicas"""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': clean_response}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Investigate DB alarm")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify the response is unchanged
        assert report.strip() == clean_response.strip()
    
    @patch('bedrock_client.boto3.client')
    def test_cleanup_multiple_trailing_sections(self, mock_boto_client):
        """Test cleanup when there are multiple trailing sections after tool call."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        response_with_multiple_trailing = """### 🚨 EXECUTIVE SUMMARY
S3 bucket access denied errors detected in data pipeline.

### 📊 ROOT CAUSE ANALYSIS
IAM role missing s3:GetObject permission for new bucket.

### 🔧 IMMEDIATE ACTIONS
1. Update IAM role with correct S3 permissions
2. Verify cross-account access if applicable

TOOL: python_executor
```python
# Check IAM role permissions
iam = boto3.client('iam')
role = iam.get_role(RoleName='data-pipeline-role')
print(f"Role ARN: {role['Role']['Arn']}")
policies = iam.list_attached_role_policies(RoleName='data-pipeline-role')
result = {"policies": policies['AttachedPolicies']}
```

### Next Steps
After retrieving the IAM configuration, we should:
1. Analyze attached policies
2. Check for S3 permissions
3. Verify bucket policies

The investigation will continue with detailed permission analysis."""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': response_with_multiple_trailing}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Investigate S3 alarm")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify all trailing content is removed
        assert "TOOL: python_executor" not in report
        assert "### Next Steps" not in report
        assert "After retrieving the IAM" not in report
        assert "The investigation will continue" not in report
        
        # Verify main content preserved
        assert "S3 bucket access denied" in report
        assert "### 🔧 IMMEDIATE ACTIONS" in report
        assert "Update IAM role" in report
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.logger')
    def test_cleanup_logs_warning(self, mock_logger, mock_boto_client):
        """Test that cleanup logs a warning when removing trailing tool calls."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        response_with_tool = """### 🚨 SUMMARY
Quick investigation complete.

TOOL: python_executor
```python
print("Additional analysis")
```"""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': response_with_tool}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Test")
        
        # Result should be a dict
        assert isinstance(result, dict)
        
        # Verify logger was called with debug messages
        mock_logger.debug.assert_called()
        
        # Check all debug calls to find the one about removal
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        
        # The cleanup should have happened and logged
        cleanup_log_found = False
        for call in debug_calls:
            if "Removed trailing tool call" in call:
                cleanup_log_found = True
                assert "original:" in call
                assert "cleaned:" in call
                break
        
        assert cleanup_log_found, f"Expected cleanup log not found. Debug calls: {debug_calls}"
    
    @patch('bedrock_client.boto3.client')
    def test_cleanup_preserves_code_blocks_in_analysis(self, mock_boto_client):
        """Test that legitimate code blocks in the analysis are preserved."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        response_with_example_code = """### 🚨 EXECUTIVE SUMMARY
Lambda function needs configuration update.

### 🔧 IMMEDIATE ACTIONS
1. Update the Lambda function with this configuration:
   ```python
   # Recommended timeout configuration
   TIMEOUT = 60
   MEMORY = 512
   ```
2. Apply these environment variables:
   ```json
   {
     "MAX_RETRIES": "3",
     "BACKOFF_BASE": "2"
   }
   ```

### 📝 ADDITIONAL NOTES
Use the above configuration for optimal performance.

TOOL: python_executor
```python
# This should be removed
print("Checking current config")
```"""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': response_with_example_code}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Test config")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify trailing tool is removed
        assert "This should be removed" not in report
        assert "Checking current config" not in report
        
        # Verify legitimate code blocks are preserved
        assert "# Recommended timeout configuration" in report
        assert "TIMEOUT = 60" in report
        assert '"MAX_RETRIES": "3"' in report
    
    @patch('bedrock_client.boto3.client')
    def test_cleanup_case_insensitive(self, mock_boto_client):
        """Test that cleanup works with different case variations."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        response_with_mixed_case = """### 🚨 SUMMARY
Investigation complete.

Tool: Python_Executor
```python
print("This should be removed")
```"""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': response_with_mixed_case}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Test case")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify case-insensitive cleanup
        assert "Tool: Python_Executor" not in report
        assert "This should be removed" not in report
        assert "### 🚨 SUMMARY" in report
        assert "Investigation complete." in report
    
    @patch('bedrock_client.boto3.client')
    def test_cleanup_with_real_world_example(self, mock_boto_client):
        """Test cleanup with a real-world example similar to actual email reports."""
        mock_bedrock = MagicMock()
        mock_lambda = MagicMock()
        mock_boto_client.side_effect = [mock_bedrock, mock_lambda]
        
        with patch.dict(os.environ, {
            'BEDROCK_REGION': 'us-east-2',
            'AWS_REGION': 'us-east-2'
        }):
            bedrock_client = BedrockAgentClient(
                model_id='us.amazon.nova-premier-v1:0',
                tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
            )
        
        # This mimics the actual problematic response from Nova Premier
        real_world_response = """### 🚨 EXECUTIVE SUMMARY
The CloudWatch alarm "data-processor-errors-prod" triggered due to 5 processing errors in the last minute. This indicates potential failures in the data processing Lambda function.

### 🔍 INVESTIGATION DETAILS

#### Commands Executed:
1. Retrieved CloudWatch Logs for the Lambda function (last 30 minutes)
2. Fetched CloudWatch Metrics for ProcessorErrors (last 2 hours)

#### Key Findings:
- Lambda function "data-processor-prod" had 5 error invocations at 14:30 UTC
- Error pattern shows "ValidationException" from DynamoDB calls
- Function uses execution role with basic Lambda permissions

### 📊 ROOT CAUSE ANALYSIS
The alarm triggered due to 5 consecutive errors in the data-processor-prod Lambda function caused by ValidationException from DynamoDB.

### 💥 IMPACT ASSESSMENT
- **Affected Resources**: data-processor-prod Lambda, dependent DynamoDB table
- **Business Impact**: Potential loss of data processing pipeline
- **Severity Level**: High

### 🔧 IMMEDIATE ACTIONS
1. **Validate Lambda Code**: Check recent deployments for schema changes
2. **Fix DynamoDB Parameters**: Update Lambda to handle validation errors
3. **Monitor Recovery**: Watch error metrics for 15 minutes post-fix

### 🛡️ PREVENTION MEASURES
- Add input validation to Lambda handler
- Implement dead-letter queue for failed records

TOOL: python_executor
```python
# First get CloudWatch Logs for the Lambda function
print("Fetching CloudWatch Logs for data-processor-prod Lambda...");
logs_client = boto3.client('logs', region_name='us-east-2');

log_group_name = f"/aws/lambda/data-processor-prod";

streams_response = logs_client.describe_log_streams(
    logGroupName=log_group_name,
    orderBy='LastEventTime',
    descending=True,
    limit=5
);

print(f"Found {len(streams_response['logStreams'])} log streams");

if streams_response['logStreams']:
    latest_stream = streams_response['logStreams'][0];
    events_response = logs_client.get_log_events(
        logGroupName=log_group_name,
        logStreamName=latest_stream['logStreamName'],
        startTime=int((datetime.utcnow() - timedelta(minutes=30)).timestamp() * 1000),
        limit=50
    );
    
    error_events = [e for e in events_response['events'] if 'ERROR' in e['message']];
    print(f"Found {len(error_events)} error events in last 30 minutes");
```

I'll start by analyzing the CloudWatch Logs for the data-processor-prod Lambda function to identify the specific errors that triggered the alarm."""
        
        mock_bedrock.converse.return_value = {
            'output': {
                'message': {
                    'content': [{'text': real_world_response}]
                }
            }
        }
        
        result = bedrock_client.investigate_with_tools("Investigate data processing alarm")
        
        # Extract the report from the dict result
        assert isinstance(result, dict)
        report = result.get('report', '')
        
        # Verify all the trailing content is removed
        assert "TOOL: python_executor" not in report
        assert "```python" not in report
        assert "I'll start by analyzing" not in report
        assert "logs_client.describe_log_streams" not in report
        
        # Verify the main investigation report is intact
        assert "### 🚨 EXECUTIVE SUMMARY" in report
        assert "data-processor-errors-prod" in report
        assert "ValidationException" in report
        assert "### 🛡️ PREVENTION MEASURES" in report
        assert "Implement dead-letter queue" in report
        
        # Verify it ends cleanly at the last legitimate content
        assert report.strip().endswith("Implement dead-letter queue for failed records")