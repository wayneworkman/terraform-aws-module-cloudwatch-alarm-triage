import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import time

# Add lambda directories to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from triage_handler import handler as triage_handler
from bedrock_client import BedrockAgentClient

class TestProductionReadiness:
    """Test production readiness scenarios."""
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic'
    })
    def test_bedrock_failure_fallback(self, sample_alarm_event, mock_lambda_context):
        """Test that Bedrock failures provide useful fallback analysis."""
        with patch('triage_handler.BedrockAgentClient') as mock_bedrock_class:
            with patch('triage_handler.boto3.client') as mock_boto3:
                # Setup mocks - Bedrock fails completely
                mock_bedrock = Mock()
                mock_bedrock.investigate_with_tools.side_effect = Exception("Bedrock service unavailable")
                mock_bedrock_class.return_value = mock_bedrock
                
                mock_sns = Mock()
                mock_boto3.return_value = mock_sns
                
                # Call handler
                result = triage_handler(sample_alarm_event, mock_lambda_context)
                
                # Should still complete successfully with fallback
                assert result['statusCode'] == 200
                
                # Verify fallback notification was sent
                mock_sns.publish.assert_called_once()
                sns_call = mock_sns.publish.call_args
                assert 'Investigation Error - Bedrock Unavailable' in sns_call[1]['Message']
                assert 'Manual Investigation Required' in sns_call[1]['Message']
                assert 'test-lambda-errors' in sns_call[1]['Message']
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_throttling_retry_logic(self, mock_boto3_client):
        """Test Bedrock throttling retry logic with exponential backoff."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Setup throttling then success
        throttling_error = Exception("ThrottlingException: Request was throttled")
        success_response = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'Analysis complete'
                    }]
                }
            }
        }
        mock_bedrock_client.converse.side_effect = [
            throttling_error,  # First call fails
            success_response   # Retry succeeds
        ]
        
        with patch('bedrock_client.time.sleep') as mock_sleep:
            client = BedrockAgentClient('test-model', 'test-arn')
            
            # This should retry and succeed
            result = client.investigate_with_tools("Test prompt")
            
            assert isinstance(result, dict) and result.get("report", "") == 'Analysis complete'
            assert mock_bedrock_client.converse.call_count == 2
            mock_sleep.assert_called_once_with(2)  # First retry delay
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_max_retries_exceeded(self, mock_boto3_client):
        """Test that max retries are respected for throttling."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Always return throttling error
        throttling_error = Exception("ThrottlingException: Request was throttled")
        mock_bedrock_client.converse.side_effect = throttling_error
        
        with patch('bedrock_client.time.sleep') as mock_sleep:
            client = BedrockAgentClient('test-model', 'test-arn')
            
            # Should eventually return fallback after max retries
            result = client.investigate_with_tools("Test prompt")
            
            # Should return fallback error message
            assert isinstance(result, dict)
            assert "Investigation Error" in result.get("report", "")
            assert "ThrottlingException" in result.get("report", "")
            # Should try initial + 3 retries = 4 total calls
            assert mock_bedrock_client.converse.call_count == 4
            # Should have 3 sleep calls (for 3 retries)
            assert mock_sleep.call_count == 3
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_non_throttling_error_immediate_failure(self, mock_boto3_client):
        """Test that non-throttling errors fail immediately without retries."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Non-throttling error
        validation_error = Exception("ValidationException: Invalid model ID")
        mock_bedrock_client.converse.side_effect = validation_error
        
        with patch('bedrock_client.time.sleep') as mock_sleep:
            client = BedrockAgentClient('test-model', 'test-arn')
            
            # Should return fallback immediately
            result = client.investigate_with_tools("Test prompt")
            
            # Should return fallback error message  
            assert isinstance(result, dict)
            assert "Investigation Error" in result.get("report", "")
            assert "ValidationException" in result.get("report", "")
            # Should only try once
            assert mock_bedrock_client.converse.call_count == 1
            # Should not sleep/retry
            mock_sleep.assert_not_called()
    
    @patch('bedrock_client.boto3.client')
    def test_tool_lambda_timeout_handling(self, mock_boto3_client):
        """Test handling when tool Lambda times out."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock Bedrock requesting tool then providing final response
        bedrock_responses = [
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'TOOL: python_executor\n```python\nlogs = boto3.client(\"logs\"); result = \"log events\"\n```'
                        }]
                    }
                }
            },
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Tool timed out but continuing with basic analysis based on alarm data.'
                        }]
                    }
                }
            }
        ]
        
        mock_bedrock_client.converse.side_effect = bedrock_responses
        
        # Mock Lambda timeout
        mock_lambda_client.invoke.side_effect = Exception("Lambda timeout")
        
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Should handle timeout gracefully and continue
        assert isinstance(result, dict) and 'Tool timed out but continuing' in result.get("report", "")
    
    def test_tool_lambda_memory_and_performance_limits(self, mock_lambda_context):
        """Test tool Lambda handles large outputs and memory constraints."""
        from tool_handler import handler as tool_handler
        
        # Test large output handling (no longer truncated)
        event = {
            'command': 'result = "A" * 100000'  # 100KB of data
        }
        
        result = tool_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Should NOT be truncated anymore
        assert len(body['output']) >= 100000  # Full 100KB should be present
        
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic'
    })
    def test_token_limit_handling(self, sample_alarm_event, mock_lambda_context):
        """Test handling when model limits are reached."""
        with patch('triage_handler.BedrockAgentClient') as mock_bedrock_class:
            with patch('triage_handler.boto3.client') as mock_boto3:
                # Setup mocks
                mock_bedrock = Mock()
                mock_bedrock.investigate_with_tools.return_value = {"report": "Analysis completed", "full_context": [], "iteration_count": 1, "tool_calls": []}
                mock_bedrock_class.return_value = mock_bedrock
                
                mock_sns = Mock()
                mock_boto3.return_value = mock_sns
                
                # Call handler
                result = triage_handler(sample_alarm_event, mock_lambda_context)
                
                # Verify BedrockAgentClient was initialized correctly (no max_tokens)
                mock_bedrock_class.assert_called_with(
                    model_id='anthropic.claude-opus-4-1-20250805-v1:0',
                    tool_lambda_arn='arn:aws:lambda:us-east-2:123456789012:function:tool-lambda'
                )
                
                assert result['statusCode'] == 200