import pytest
import json
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from bedrock_client import BedrockAgentClient

class TestBedrockClientEdgeCases:
    """Test edge cases for Bedrock client."""
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_tool_execution_with_complex_error_response(self, mock_sleep, mock_boto3_client):
        """Test tool execution when Lambda returns complex error structure."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock Bedrock requesting tool with Converse API format
        bedrock_response = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'TOOL: python_executor\n```python\nec2 = boto3.client("ec2")\nresponse = ec2.describe_instances()\nprint(response)\n```'
                    }]
                }
            }
        }
        
        mock_bedrock_client.converse.return_value = bedrock_response
        
        # Mock complex Lambda error response
        error_response = {
            'StatusCode': 500,  # Lambda execution error
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'output': 'Internal Lambda error occurred',
                    'error_details': {
                        'type': 'RuntimeError',
                        'message': 'Unexpected error in Lambda execution'
                    }
                })
            }).encode())
        }
        
        mock_lambda_client.invoke.return_value = error_response
        
        client = BedrockAgentClient('test-model', 'test-arn')
        
        # Should handle complex error response gracefully
        result = client.investigate_with_tools("Test prompt")
        
        # Should exhaust iterations and return default message 
        assert isinstance(result, dict) and "Investigation completed but no analysis was generated" in result.get("report", "")
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_tool_execution_lambda_timeout_scenario(self, mock_sleep, mock_boto3_client):
        """Test tool execution when Lambda times out."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock Bedrock requesting tool then final response with Converse API
        bedrock_responses = [
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'TOOL: python_executor\n```python\nlogs = boto3.client("logs")\nresponse = logs.filter_log_events(logGroupName="/aws/lambda/test")\nprint(response)\n```'
                        }]
                    }
                }
            },
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Continuing analysis despite tool timeout.'
                        }]
                    }
                }
            }
        ]
        
        mock_bedrock_client.converse.side_effect = bedrock_responses
        
        # Mock Lambda timeout exception
        from botocore.exceptions import ClientError
        timeout_error = ClientError(
            error_response={'Error': {'Code': 'TooManyRequestsException', 'Message': 'Rate exceeded'}},
            operation_name='Invoke'
        )
        mock_lambda_client.invoke.side_effect = timeout_error
        
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Should complete despite tool error
        assert isinstance(result, dict) and 'Continuing analysis despite tool timeout' in result.get("report", "")
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_bedrock_response_parsing_edge_cases(self, mock_sleep, mock_boto3_client):
        """Test parsing of various Bedrock response formats."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Test exception from Converse API (simulating malformed response)
        mock_bedrock_client.converse.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
        
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Should handle malformed response gracefully with fallback message
        assert isinstance(result, dict) and "Investigation Error" in result.get("report", "")
        assert isinstance(result, dict) and "An error occurred while invoking model" in result.get("report", "")