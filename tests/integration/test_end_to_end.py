import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add lambda directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from triage_handler import handler as triage_handler
from tool_handler import handler as tool_handler

class TestEndToEndIntegration:
    """Integration tests for the complete alarm triage workflow."""
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000',
        'DYNAMODB_TABLE': 'test-table',
        'INVESTIGATION_WINDOW_HOURS': '1'
    })
    @patch('boto3.resource')
    @patch('boto3.client')
    def test_complete_alarm_investigation_workflow(self, mock_boto3_client, mock_boto3_resource, sample_alarm_event, mock_lambda_context):
        """Test the complete workflow from alarm to notification."""
        # Setup mocks
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock() 
        mock_sns_client = Mock()
        
        # Mock DynamoDB
        mock_dynamodb_table = Mock()
        mock_dynamodb_table.get_item.return_value = {}  # No previous investigation
        mock_dynamodb_table.put_item.return_value = {}
        mock_dynamodb_resource = Mock()
        mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
        mock_boto3_resource.return_value = mock_dynamodb_resource
        
        # Mock boto3 client creation
        def client_factory(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                return mock_bedrock_client
            elif service_name == 'lambda':
                return mock_lambda_client
            elif service_name == 'sns':
                return mock_sns_client
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        # Mock Bedrock conversation
        bedrock_responses = [
            # First response - Claude requests tool
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-1',
                            'name': 'aws_investigator',
                            'input': {
                                'type': 'cli',
                                'command': 'aws logs filter-log-events --log-group-name /aws/lambda/test-function --start-time 1672531200000'
                            }
                        }
                    ]
                }).encode())
            },
            # Second response - Claude provides analysis
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'text',
                            'text': '''### 🚨 EXECUTIVE SUMMARY
Lambda function test-function is experiencing high error rates due to permission issues accessing EC2 resources.

### 🔍 INVESTIGATION DETAILS

#### Commands Executed:
- Checked CloudWatch Logs for error patterns
- Analyzed IAM role permissions  
- Retrieved recent metric data

#### Key Findings:
- AccessDenied errors for EC2 describe operations
- Lambda role missing EC2 permissions
- Error rate increased 2 hours ago

### 📊 ROOT CAUSE ANALYSIS
The Lambda function is failing because the execution role lacks EC2:DescribeInstances permission.

### 💥 IMPACT ASSESSMENT
- **Affected Resources**: test-function Lambda
- **Business Impact**: Function completely non-functional
- **Severity Level**: High  
- **Users Affected**: All users of this function

### 🔧 IMMEDIATE ACTIONS
1. Add EC2 permissions to Lambda role
2. Test function execution
3. Monitor error rates

### 🛡️ PREVENTION MEASURES
- Implement IAM policy validation in CI/CD
- Add comprehensive integration tests

### 📈 MONITORING RECOMMENDATIONS  
- Add specific alarm for permission errors
- Monitor IAM policy changes

### 📝 ADDITIONAL NOTES
This appears to be caused by recent security policy tightening.'''
                        }
                    ]
                }).encode())
            }
        ]
        
        mock_bedrock_client.invoke_model.side_effect = bedrock_responses
        
        # Mock tool Lambda response
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'output': '''ERROR: AccessDeniedException when calling the DescribeInstances operation: User: arn:aws:sts::123456789012:assumed-role/test-function-role/test-function is not authorized to perform: ec2:DescribeInstances'''
                })
            }).encode())
        }
        
        # Call the triage handler
        result = triage_handler(sample_alarm_event, mock_lambda_context)
        
        # Verify successful processing
        assert result['statusCode'] == 200
        response_body = json.loads(result['body'])
        assert response_body['investigation_complete'] is True
        assert response_body['alarm'] == 'test-lambda-errors'
        
        # Verify tool Lambda was invoked
        mock_lambda_client.invoke.assert_called_once()
        tool_call = mock_lambda_client.invoke.call_args
        assert 'tool-lambda' in tool_call[1]['FunctionName']
        
        # Verify SNS notification was sent
        mock_sns_client.publish.assert_called_once()
        sns_call = mock_sns_client.publish.call_args
        assert 'test-topic' in sns_call[1]['TopicArn']
        assert 'CloudWatch Alarm Investigation' in sns_call[1]['Subject']
        assert 'EXECUTIVE SUMMARY' in sns_call[1]['Message']
        assert 'AccessDenied' in sns_call[1]['Message']
    
    def test_tool_lambda_cli_execution(self, mock_lambda_context):
        """Test tool Lambda CLI command execution."""
        event = {
            'type': 'cli',
            'command': 'aws sts get-caller-identity'
        }
        
        # Mock subprocess
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='{"Account": "123456789012", "UserId": "test-user", "Arn": "arn:aws:iam::123456789012:user/test"}',
                stderr=''
            )
            
            result = tool_handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
            assert '123456789012' in body['output']
    
    def test_tool_lambda_python_execution(self, mock_lambda_context):
        """Test tool Lambda Python execution."""
        event = {
            'type': 'python',
            'command': '''
import json
import boto3

# Mock a typical investigation task
result = json.dumps({
    "alarm_type": "Lambda errors",
    "investigation": "Found permission issues",
    "recommendation": "Add EC2 permissions to role"
}, indent=2)
'''
        }
        
        result = tool_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Lambda errors' in body['output']
        assert 'permission issues' in body['output']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'basic',
        'MAX_TOKENS': '10000',
        'DYNAMODB_TABLE': 'test-table',
        'INVESTIGATION_WINDOW_HOURS': '1'
    })
    @patch('boto3.resource')
    @patch('boto3.client')
    def test_basic_investigation_depth(self, mock_boto3_client, mock_boto3_resource, sample_alarm_event, mock_lambda_context):
        """Test workflow with basic investigation depth."""
        # Setup mocks similar to comprehensive test but with basic depth
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        mock_sns_client = Mock()
        
        # Mock DynamoDB
        mock_dynamodb_table = Mock()
        mock_dynamodb_table.get_item.return_value = {}
        mock_dynamodb_table.put_item.return_value = {}
        mock_dynamodb_resource = Mock()
        mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
        mock_boto3_resource.return_value = mock_dynamodb_resource
        
        def client_factory(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                return mock_bedrock_client
            elif service_name == 'lambda':
                return mock_lambda_client
            elif service_name == 'sns':
                return mock_sns_client
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        # Mock basic response (fewer tool calls)
        mock_bedrock_client.invoke_model.return_value = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': '''### 🚨 EXECUTIVE SUMMARY
Quick analysis shows Lambda errors due to permissions.

### 🔧 IMMEDIATE ACTIONS
1. Check IAM role permissions
2. Add EC2 access if needed'''
                    }
                ]
            }).encode())
        }
        
        result = triage_handler(sample_alarm_event, mock_lambda_context)
        
        # Verify processing completed
        assert result['statusCode'] == 200
        
        # Verify SNS notification contains basic analysis
        mock_sns_client.publish.assert_called_once()
        sns_call = mock_sns_client.publish.call_args
        assert 'Quick analysis' in sns_call[1]['Message']
    
    def test_tool_lambda_iam_based_security(self, mock_lambda_context):
        """Test that commands execute but would be restricted by IAM in production."""
        commands = [
            {'type': 'cli', 'command': 'aws ec2 terminate-instances --instance-ids i-1234567890abcdef0'},
            {'type': 'cli', 'command': 'aws iam delete-role --role-name test-role'},
            {'type': 'python', 'command': 'import boto3; client = boto3.client("ec2"); result = "Commands execute, IAM blocks dangerous operations"'}
        ]
        
        for event in commands:
            with patch('tool_handler.subprocess.run') as mock_run:
                # Mock IAM AccessDenied response
                mock_run.return_value = Mock(
                    returncode=1,
                    stdout='',
                    stderr='An error occurred (AccessDenied) when calling the TerminateInstances operation: User is not authorized'
                )
                
                result = tool_handler(event, mock_lambda_context)
                
                # Commands execute but return IAM errors
                assert result['statusCode'] == 200
                body = json.loads(result['body'])
                if event['type'] == 'cli':
                    assert 'AccessDenied' in body['output'] or 'Command failed' in body['output']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000',
        'DYNAMODB_TABLE': 'test-table',
        'INVESTIGATION_WINDOW_HOURS': '1'
    })
    @patch('boto3.resource')
    @patch('boto3.client')
    def test_tool_lambda_failure_handling(self, mock_boto3_client, mock_boto3_resource, sample_alarm_event, mock_lambda_context):
        """Test that tool Lambda failures are handled gracefully."""
        # Setup mocks
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        mock_sns_client = Mock()
        
        # Mock DynamoDB
        mock_dynamodb_table = Mock()
        mock_dynamodb_table.get_item.return_value = {}
        mock_dynamodb_table.put_item.return_value = {}
        mock_dynamodb_resource = Mock()
        mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
        mock_boto3_resource.return_value = mock_dynamodb_resource
        
        def client_factory(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                return mock_bedrock_client
            elif service_name == 'lambda':
                return mock_lambda_client
            elif service_name == 'sns':
                return mock_sns_client
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        # Mock tool Lambda failure
        mock_lambda_client.invoke.side_effect = Exception("Tool Lambda failed")
        
        # Mock Bedrock to request tool then provide fallback analysis
        bedrock_responses = [
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-1',
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws logs filter-log-events'}
                        }
                    ]
                }).encode())
            },
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Tool execution failed but providing basic analysis based on alarm data.'
                        }
                    ]
                }).encode())
            }
        ]
        
        mock_bedrock_client.invoke_model.side_effect = bedrock_responses
        
        result = triage_handler(sample_alarm_event, mock_lambda_context)
        
        # Should still complete successfully
        assert result['statusCode'] == 200
        
        # Should send notification despite tool failure
        mock_sns_client.publish.assert_called_once()
    
    def test_alarm_format_variations(self, mock_lambda_context):
        """Test handling of different alarm event formats."""
        # CloudWatch Events format
        cw_events_format = {
            "source": "aws.cloudwatch",
            "detail": {
                "alarmData": {
                    "alarmName": "test-alarm-cw-events",
                    "state": {"value": "ALARM"}
                }
            }
        }
        
        # Direct alarm format  
        direct_format = {
            "alarmName": "test-alarm-direct",
            "state": {"value": "ALARM"}
        }
        
        # Manual test format
        manual_format = {
            "source": "manual-test"
        }
        
        test_cases = [
            (cw_events_format, "test-alarm-cw-events"),
            (direct_format, "test-alarm-direct"), 
            (manual_format, "Manual Test Alarm")
        ]
        
        for event_format, expected_alarm_name in test_cases:
            with patch.dict(os.environ, {
                'BEDROCK_MODEL_ID': 'test-model',
                'TOOL_LAMBDA_ARN': 'test-arn',
                'SNS_TOPIC_ARN': 'test-topic',
                'INVESTIGATION_DEPTH': 'basic',
                'MAX_TOKENS': '1000'
            }):
                with patch('triage_handler.BedrockAgentClient') as mock_bedrock:
                    with patch('boto3.client') as mock_boto3:
                        mock_bedrock.return_value.investigate_with_tools.return_value = "Analysis"
                        
                        result = triage_handler(event_format, mock_lambda_context)
                        
                        assert result['statusCode'] == 200
                        response_body = json.loads(result['body'])
                        assert response_body['alarm'] == expected_alarm_name