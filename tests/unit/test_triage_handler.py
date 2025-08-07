import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add lambda directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from triage_handler import handler, format_notification

class TestTriageHandler:
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000'
    })
    def test_handler_alarm_state(self, sample_alarm_event, mock_lambda_context):
        """Test handler processes ALARM state correctly."""
        with patch('triage_handler.BedrockAgentClient') as mock_bedrock_class:
            with patch('triage_handler.boto3.client') as mock_boto3:
                # Setup mocks
                mock_bedrock = Mock()
                mock_bedrock.investigate_with_tools.return_value = "Test analysis result"
                mock_bedrock_class.return_value = mock_bedrock
                
                mock_sns = Mock()
                mock_boto3.return_value = mock_sns
                
                # Call handler
                result = handler(sample_alarm_event, mock_lambda_context)
                
                # Assertions
                assert result['statusCode'] == 200
                assert json.loads(result['body'])['investigation_complete'] is True
                assert json.loads(result['body'])['alarm'] == 'test-lambda-errors'
                
                # Verify Bedrock was called
                mock_bedrock.investigate_with_tools.assert_called_once()
                
                # Verify SNS was called
                mock_sns.publish.assert_called_once()
                sns_call = mock_sns.publish.call_args
                assert 'test-topic' in sns_call[1]['TopicArn']
                assert 'CloudWatch Alarm Investigation' in sns_call[1]['Subject']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000'
    })
    def test_handler_ok_state(self, sample_alarm_event, mock_lambda_context):
        """Test handler skips OK state."""
        # Create a copy and modify to OK state
        ok_event = sample_alarm_event.copy()
        ok_event['alarmData'] = sample_alarm_event['alarmData'].copy()
        ok_event['alarmData']['state'] = sample_alarm_event['alarmData']['state'].copy()
        ok_event['alarmData']['state']['value'] = 'OK'
        
        # Call handler
        result = handler(ok_event, mock_lambda_context)
        
        # Assertions
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'Skipped non-alarm state' in body['message']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000'
    })
    @patch('boto3.client')
    @patch('triage_handler.BedrockAgentClient')
    def test_handler_bedrock_error(self, mock_bedrock_class, mock_boto3_client, sample_alarm_event, mock_lambda_context):
        """Test handler handles Bedrock errors gracefully."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_bedrock.investigate_with_tools.side_effect = Exception("Bedrock error")
        mock_bedrock_class.return_value = mock_bedrock
        
        mock_sns = Mock()
        mock_boto3_client.return_value = mock_sns
        
        # Call handler
        result = handler(sample_alarm_event, mock_lambda_context)
        
        # Assertions - now returns success with fallback analysis
        assert result['statusCode'] == 200
        assert json.loads(result['body'])['investigation_complete'] is True
        
        # Verify notification was sent with fallback analysis
        mock_sns.publish.assert_called_once()
        sns_call = mock_sns.publish.call_args
        assert 'Investigation Error - Bedrock Unavailable' in sns_call[1]['Message']
        assert 'Bedrock error' in sns_call[1]['Message']
    
    def test_format_notification(self, sample_alarm_event):
        """Test notification formatting."""
        analysis = "This is a test analysis"
        
        result = format_notification(
            "test-alarm",
            "ALARM",
            analysis,
            sample_alarm_event
        )
        
        assert "test-alarm" in result
        assert "ALARM" in result
        assert "This is a test analysis" in result
        assert "us-east-2" in result
        assert "123456789012" in result
        assert "console.aws.amazon.com" in result
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'basic',
        'MAX_TOKENS': '10000'
    })
    @patch('boto3.client')
    @patch('triage_handler.BedrockAgentClient')
    def test_handler_different_investigation_depths(self, mock_bedrock_class, mock_boto3_client, sample_alarm_event, mock_lambda_context):
        """Test handler with different investigation depths."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_bedrock.investigate_with_tools.return_value = "Basic analysis"
        mock_bedrock_class.return_value = mock_bedrock
        
        mock_sns = Mock()
        mock_boto3_client.return_value = mock_sns
        
        # Call handler
        result = handler(sample_alarm_event, mock_lambda_context)
        
        # Verify correct depth was passed
        mock_bedrock_class.assert_called_with(
            model_id='anthropic.claude-opus-4-1-20250805-v1:0',
            tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
            max_tokens=10000
        )
    
    def test_handler_direct_alarm_format(self, mock_lambda_context):
        """Test handler with direct alarm format (not wrapped in CloudWatch Events)."""
        direct_event = {
            "alarmName": "direct-alarm",
            "state": {
                "value": "ALARM",
                "reason": "Test reason"
            }
        }
        
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
                    
                    result = handler(direct_event, mock_lambda_context)
                    
                    assert result['statusCode'] == 200
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000'
    })
    @patch('boto3.client')
    @patch('triage_handler.BedrockAgentClient')
    def test_handler_sns_error_handling(self, mock_bedrock_class, mock_boto3_client, sample_alarm_event, mock_lambda_context):
        """Test handler handles SNS errors gracefully."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_bedrock.investigate_with_tools.side_effect = Exception("Test error")
        mock_bedrock_class.return_value = mock_bedrock
        
        mock_sns = Mock()
        mock_sns.publish.side_effect = Exception("SNS error")
        mock_boto3_client.return_value = mock_sns
        
        # Call handler - should not crash despite SNS error
        result = handler(sample_alarm_event, mock_lambda_context)
        
        # Assertions - SNS error should cause overall failure
        assert result['statusCode'] == 500
        assert 'SNS error' in json.loads(result['body'])['error']