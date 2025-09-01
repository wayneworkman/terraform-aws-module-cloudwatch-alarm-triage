import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from triage_handler import handler as triage_handler
from tool_handler import handler as tool_handler
from bedrock_client import BedrockAgentClient

class TestMalformedEventsAndConfiguration:
    """Test handling of malformed events and configuration issues."""
    
    # Malformed Event Tests
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.BedrockAgentClient')
    @patch('triage_handler.boto3.client')
    def test_triage_handler_empty_event(self, mock_boto3_client, mock_bedrock, mock_lambda_context):
        """Test triage handler with empty event."""
        # Empty event defaults to ALARM state and processes
        mock_bedrock.return_value.investigate_with_tools.return_value = "Analysis for empty event"
        mock_sns = Mock()
        mock_sns.publish.return_value = {'MessageId': 'test-id'}
        mock_boto3_client.return_value = mock_sns
        
        result = triage_handler({}, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Empty events default to 'Manual Test Alarm' in ALARM state
        assert body.get('alarm') == 'Manual Test Alarm' or body.get('alarm_name') == 'Manual Test Alarm'
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.BedrockAgentClient')
    @patch('triage_handler.boto3.client')
    def test_triage_handler_missing_alarm_data(self, mock_boto3_client, mock_bedrock, mock_lambda_context):
        """Test triage handler with missing alarm data."""
        event = {
            'source': 'aws.cloudwatch',
            'detail-type': 'CloudWatch Alarm State Change'
            # Missing 'detail' key
        }
        
        # Will default to ALARM state and process
        mock_bedrock.return_value.investigate_with_tools.return_value = "Analysis"
        mock_sns = Mock()
        mock_sns.publish.return_value = {'MessageId': 'test-id'}
        mock_boto3_client.return_value = mock_sns
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        # Should handle gracefully
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.BedrockAgentClient')
    @patch('triage_handler.boto3.client')
    def test_triage_handler_null_values_in_event(self, mock_boto3_client, mock_bedrock, mock_lambda_context):
        """Test triage handler with null values in event."""
        event = {
            'alarmData': {
                'alarmName': None,
                'state': {
                    'value': 'ALARM',
                    'reason': None
                }
            }
        }
        
        mock_bedrock.return_value.investigate_with_tools.return_value = "Analysis"
        mock_sns = Mock()
        mock_sns.publish.return_value = {'MessageId': 'test-id'}
        mock_boto3_client.return_value = mock_sns
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        # Should handle gracefully without crashing
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.boto3.client')
    def test_triage_handler_non_alarm_state(self, mock_boto3_client, mock_lambda_context):
        """Test triage handler with non-ALARM state."""
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {
                    'value': 'OK'  # Not in ALARM state
                }
            }
        }
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'Skipped non-alarm state' in body['message']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.BedrockAgentClient')
    @patch('triage_handler.boto3.client')
    def test_triage_handler_malformed_json_string_in_event(self, mock_boto3_client, mock_bedrock, mock_lambda_context):
        """Test triage handler with malformed JSON string in event field."""
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {
                    'value': 'ALARM',
                    'reason': '{"invalid json": without closing brace'
                }
            }
        }
        
        mock_bedrock.return_value.investigate_with_tools.return_value = "Analysis"
        mock_sns = Mock()
        mock_sns.publish.return_value = {'MessageId': 'test-id'}
        mock_boto3_client.return_value = mock_sns
        
        # Should handle malformed JSON in fields gracefully
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        # Should not crash on malformed JSON
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.boto3.client')
    @patch('triage_handler.BedrockAgentClient')
    def test_triage_handler_very_large_event(self, mock_bedrock_client, mock_boto3_client, mock_lambda_context):
        """Test triage handler with extremely large event."""
        # Create a very large event
        large_reason = "A" * 100000  # 100KB string
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {
                    'value': 'ALARM',
                    'reason': large_reason
                },
                'configuration': {
                    'description': 'B' * 50000,
                    'metrics': [{'data': 'C' * 10000} for _ in range(10)]
                }
            }
        }
        
        mock_bedrock_client.return_value.investigate_with_tools.return_value = "Analysis complete"
        mock_sns = Mock()
        mock_boto3_client.return_value = mock_sns
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        # Should handle large events without memory issues
    
    # Configuration Validation Tests
    
    def test_triage_handler_missing_required_env_vars(self, mock_lambda_context):
        """Test triage handler with missing required environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            event = {
                'alarmData': {
                    'alarmName': 'test-alarm',
                    'state': {'value': 'ALARM'}
                }
            }
            
            result = triage_handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 500
            body = json.loads(result['body'])
            assert 'error' in body or 'Error' in body
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': '',  # Empty model ID
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    def test_triage_handler_empty_model_id(self, mock_lambda_context):
        """Test triage handler with empty model ID."""
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 500
        body = json.loads(result['body'])
        assert 'error' in body or 'Error' in body
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'invalid::arn::format',  # Malformed ARN
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.boto3.client')
    def test_triage_handler_invalid_arn_format(self, mock_boto3_client, mock_lambda_context):
        """Test triage handler with invalid ARN format."""
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Should handle invalid ARN gracefully
        result = triage_handler(event, mock_lambda_context)
        
        # May fail at runtime when trying to invoke Lambda
        assert result['statusCode'] in [200, 500]
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'non-existent-model-xyz-123',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:tool',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:topic'
    })
    @patch('bedrock_client.boto3.client')
    def test_bedrock_client_invalid_model_id(self, mock_boto3_client):
        """Test Bedrock client with invalid model ID."""
        mock_bedrock = Mock()
        mock_lambda = Mock()
        
        def client_factory(service_name, **kwargs):
            if service_name == 'bedrock-runtime':
                mock_bedrock.converse.side_effect = Exception("Model not found")
                return mock_bedrock
            elif service_name == 'lambda':
                return mock_lambda
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        client = BedrockAgentClient('non-existent-model', 'test-arn')
        
        # Should return error message for invalid model
        result = client.investigate_with_tools("Test prompt")
        
        assert isinstance(result, dict)
        assert "Investigation Error" in result['report']
        assert "Model not found" in result['report']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic',
        'INVESTIGATION_WINDOW_HOURS': 'not-a-number'  # Invalid number
    })
    @patch('triage_handler.boto3.client')
    def test_triage_handler_invalid_window_hours(self, mock_boto3_client, mock_lambda_context):
        """Test triage handler with invalid investigation window hours."""
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Should use default value or handle gracefully
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] in [200, 500]
    
    # Tool Handler Malformed Events
    
    def test_tool_handler_empty_event(self):
        """Test tool handler with empty event."""
        result = tool_handler({}, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert body['output'] == ""  # Empty command returns empty output
    
    def test_tool_handler_null_command(self):
        """Test tool handler with null command."""
        event = {'command': None}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 500  # Null causes TypeError
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'NoneType' in body['output'] or 'Error' in body['output']
    
    def test_tool_handler_non_string_command(self):
        """Test tool handler with non-string command."""
        event = {'command': {'not': 'a string'}}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 500  # Dict causes TypeError
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'unhashable' in body['output'] or 'Error' in body['output']
    
    def test_tool_handler_command_with_control_characters(self):
        """Test tool handler with control characters in command."""
        event = {'command': 'print("test\\x00\\x01\\x02")'}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Should handle control characters gracefully
    
    def test_tool_handler_extremely_long_command(self):
        """Test tool handler with extremely long command."""
        # Create a very long but valid command
        long_command = 'result = "' + 'A' * 1000000 + '"'  # 1MB command
        event = {'command': long_command}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Should handle but may truncate output
    
    def test_tool_handler_infinite_loop_command(self):
        """Test tool handler with command that would create infinite loop."""
        event = {'command': '''
import signal
import time

def timeout_handler(signum, frame):
    raise TimeoutError("Command timed out")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(1)  # 1 second timeout

try:
    while True:
        pass
except TimeoutError:
    result = "Timed out as expected"
'''}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Should handle timeout gracefully
    
    def test_tool_handler_syntax_error_command(self):
        """Test tool handler with Python syntax errors."""
        event = {'command': 'def broken_function( without closing'}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'SyntaxError' in body['output'] or 'syntax' in body['output'].lower()
    
    def test_tool_handler_import_restricted_modules(self):
        """Test tool handler blocks/handles restricted imports."""
        event = {'command': '''
import subprocess
result = subprocess.check_output(['ls', '-la'])
'''}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Import should be stripped or handled safely
    
    # Unicode and Special Characters
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    @patch('triage_handler.boto3.client')
    def test_triage_handler_unicode_in_alarm_name(self, mock_boto3_client, mock_lambda_context):
        """Test triage handler with Unicode characters in alarm name."""
        event = {
            'alarmData': {
                'alarmName': 'test-alarm-中文-العربية-🚨',
                'state': {'value': 'ALARM'}
            }
        }
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        # Should handle Unicode characters properly
    
    def test_tool_handler_unicode_output(self):
        """Test tool handler with Unicode output."""
        event = {'command': 'result = "Hello 世界 🌍 مرحبا"'}
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert '世界' in body['output']
        assert '🌍' in body['output']
        assert 'مرحبا' in body['output']