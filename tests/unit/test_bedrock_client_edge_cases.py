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
    def test_tool_execution_with_complex_error_response(self, mock_boto3_client):
        """Test tool execution when Lambda returns complex error structure."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock Bedrock requesting tool
        bedrock_response = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'tool-1',
                        'name': 'aws_investigator',
                        'input': {'type': 'cli', 'command': 'aws ec2 describe-instances'}
                    }
                ]
            }).encode())
        }
        
        mock_bedrock_client.invoke_model.return_value = bedrock_response
        
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
        
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        
        # Should handle complex error response gracefully
        result = client.investigate_with_tools("Test prompt")
        
        # Should exhaust iterations and return default message 
        assert "Investigation completed but no analysis was generated" in result
    
    @patch('bedrock_client.boto3.client')  
    def test_tool_execution_lambda_timeout_scenario(self, mock_boto3_client):
        """Test tool execution when Lambda times out."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock Bedrock requesting tool then final response
        bedrock_responses = [
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-1', 
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws logs filter-log-events --log-group /aws/lambda/test'}
                        }
                    ]
                }).encode())
            },
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Continuing analysis despite tool timeout.'
                        }
                    ]
                }).encode())
            }
        ]
        
        mock_bedrock_client.invoke_model.side_effect = bedrock_responses
        
        # Mock Lambda timeout exception
        from botocore.exceptions import ClientError
        timeout_error = ClientError(
            error_response={'Error': {'Code': 'TooManyRequestsException', 'Message': 'Rate exceeded'}},
            operation_name='Invoke'
        )
        mock_lambda_client.invoke.side_effect = timeout_error
        
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should complete despite tool error
        assert 'Continuing analysis despite tool timeout' in result
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_response_parsing_edge_cases(self, mock_boto3_client):
        """Test parsing of various Bedrock response formats."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Test malformed JSON response 
        malformed_response = {
            'body': Mock(read=lambda: b'{"incomplete": json')
        }
        
        mock_bedrock_client.invoke_model.return_value = malformed_response
        
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should handle malformed response gracefully with fallback message
        assert "Investigation Error" in result
        assert "An error occurred while invoking Claude" in result