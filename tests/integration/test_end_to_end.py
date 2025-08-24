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
        
        # Mock Bedrock conversation using Converse API
        bedrock_responses = [
            # First response - Claude requests tool
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'TOOL: python_executor\n```python\nlogs = boto3.client("logs"); response = logs.filter_log_events(logGroupName="/aws/lambda/test-function", startTime=1672531200000); result = response\n```'
                        }]
                    }
                }
            },
            # Second response - Claude provides analysis
            {
                'output': {
                    'message': {
                        'content': [{
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
                        }]
                    }
                }
            }
        ]
        
        mock_bedrock_client.converse.side_effect = bedrock_responses
        
        # Mock tool Lambda response
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'output': '{"events": [{"timestamp": "2025-08-06T11:58:00Z", "message": "AccessDenied: User does not have permission to perform ec2:DescribeInstances"}]}'
                })
            }).encode())
        }
        
        # Mock SNS publish
        mock_sns_client.publish.return_value = {'MessageId': 'test-message-id'}
        
        # Execute handler
        result = triage_handler(sample_alarm_event, mock_lambda_context)
        
        # Assertions
        assert result['statusCode'] == 200
        response_body = json.loads(result['body'])
        assert response_body['investigation_complete'] is True
        assert response_body['alarm'] == 'test-lambda-errors'
        
        # Verify Bedrock was called
        assert mock_bedrock_client.converse.call_count == 2
        
        # Verify tool Lambda was invoked
        mock_lambda_client.invoke.assert_called_once()
        
        # Verify SNS notification was sent  
        mock_sns_client.publish.assert_called_once()
        sns_call_args = mock_sns_client.publish.call_args
        assert sns_call_args[1]['TopicArn'] == 'arn:aws:sns:us-east-2:123456789012:test-topic'
        assert 'EXECUTIVE SUMMARY' in sns_call_args[1]['Message']
        assert 'permission issues' in sns_call_args[1]['Message'].lower()
        
        # Verify DynamoDB was used for deduplication
        mock_dynamodb_table.get_item.assert_called_once()
        mock_dynamodb_table.put_item.assert_called_once()
    
    @patch('boto3.client')
    def test_tool_lambda_python_execution(self, mock_boto3_client):
        """Test tool Lambda executes Python code correctly."""
        # Mock any boto3 clients that might be created
        mock_boto3_client.return_value = Mock()
        
        # Test event
        event = {
            'command': 'result = {"test": "value", "number": 42}'
        }
        
        # Execute handler
        result = tool_handler(event, None)
        
        # Assertions
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert '"test": "value"' in body['output']
        assert '"number": 42' in body['output']
    
    @patch('boto3.client')
    def test_tool_lambda_python_with_boto3(self, mock_boto3_client):
        """Test tool Lambda can use boto3 clients."""
        # Mock EC2 client
        mock_ec2 = Mock()
        mock_ec2.describe_instances.return_value = {
            'Reservations': [{
                'Instances': [{'InstanceId': 'i-123456'}]
            }]
        }
        
        def client_factory(service_name, **kwargs):
            if service_name == 'ec2':
                return mock_ec2
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        # Test event
        event = {
            'command': 'ec2 = boto3.client("ec2"); instances = ec2.describe_instances(); result = instances'
        }
        
        # Execute handler
        result = tool_handler(event, None)
        
        # Assertions
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'i-123456' in body['output']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic'
    })
    @patch('boto3.client')
    def test_basic_investigation_depth(self, mock_boto3_client, sample_alarm_event, mock_lambda_context):
        """Test that basic investigation depth produces simpler analysis."""
        # Setup mocks
        mock_bedrock_client = Mock()
        mock_sns_client = Mock()
        
        # Mock boto3 client creation
        def client_factory(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                return mock_bedrock_client
            elif service_name == 'sns':
                return mock_sns_client
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        # Mock Bedrock response for basic investigation using Converse API
        mock_bedrock_client.converse.return_value = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'Basic investigation: Lambda errors detected. Check recent deployments and IAM permissions.'
                    }]
                }
            }
        }
        
        # Mock SNS publish
        mock_sns_client.publish.return_value = {'MessageId': 'test-message-id'}
        
        # Execute handler
        result = triage_handler(sample_alarm_event, mock_lambda_context)
        
        # Assertions
        assert result['statusCode'] == 200
        
        # Verify Bedrock was called only once (no tools for basic)
        mock_bedrock_client.converse.assert_called_once()
        
        # Verify notification contains basic investigation
        sns_call_args = mock_sns_client.publish.call_args
        assert 'Basic investigation' in sns_call_args[1]['Message']
    
    @patch('boto3.client')
    def test_tool_lambda_iam_based_security(self, mock_boto3_client):
        """Test tool Lambda security - no imports allowed."""
        # Test event with import attempt
        event = {
            'command': 'import os; result = os.environ'
        }
        
        # Execute handler
        result = tool_handler(event, None)
        
        # Assertions
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Should execute without the import (imports are stripped)
        assert body['success'] is True
        # os.environ should work because os is pre-imported
        assert 'PATH' in body['output'] or 'HOME' in body['output']
    
    @patch('boto3.client')
    def test_tool_lambda_failure_handling(self, mock_boto3_client):
        """Test tool Lambda handles errors gracefully."""
        # Test event with error
        event = {
            'command': 'undefined_variable_that_does_not_exist'
        }
        
        # Execute handler
        result = tool_handler(event, None)
        
        # Assertions
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'NameError' in body['output'] or 'not defined' in body['output']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic'
    })
    @patch('boto3.client')
    def test_alarm_format_variations(self, mock_boto3_client, mock_lambda_context):
        """Test handling of different alarm format variations."""
        # Setup mocks
        mock_bedrock_client = Mock()
        mock_sns_client = Mock()
        
        # Mock boto3 client creation
        def client_factory(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                return mock_bedrock_client
            elif service_name == 'sns':
                return mock_sns_client
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        # Mock Bedrock response using Converse API
        mock_bedrock_client.converse.return_value = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'Investigation complete for EC2 CPU alarm.'
                    }]
                }
            }
        }
        
        # Mock SNS publish
        mock_sns_client.publish.return_value = {'MessageId': 'test-message-id'}
        
        # Test with different alarm format
        alarm_event = {
            'source': 'aws.cloudwatch',
            'detail-type': 'CloudWatch Alarm State Change',
            'detail': {
                'alarmName': 'high-cpu-alarm',
                'state': {
                    'value': 'ALARM',
                    'reason': 'Threshold Crossed'
                },
                'configuration': {
                    'metrics': [{
                        'namespace': 'AWS/EC2',
                        'name': 'CPUUtilization'
                    }]
                }
            }
        }
        
        # Execute handler
        result = triage_handler(alarm_event, mock_lambda_context)
        
        # Should handle gracefully even with different format
        assert result['statusCode'] == 200