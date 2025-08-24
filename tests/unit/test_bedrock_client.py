import pytest
import json
from unittest.mock import Mock, patch, MagicMock, call
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from bedrock_client import BedrockAgentClient

class TestBedrockAgentClient:
    
    def test_initialization(self):
        """Test BedrockAgentClient initialization."""
        with patch('bedrock_client.boto3.client') as mock_boto3:
            mock_boto3.return_value = Mock()
            
            client = BedrockAgentClient(
                model_id='test-model',
                tool_lambda_arn='test-arn'
            )
            
            assert client.model_id == 'test-model'
            assert client.tool_lambda_arn == 'test-arn'
            
            # Verify boto3 clients were created
            assert mock_boto3.call_count == 2
            # Check first call for bedrock-runtime
            call_args = mock_boto3.call_args_list[0]
            assert call_args[0][0] == 'bedrock-runtime'
            # Check second call for lambda
            call_args = mock_boto3.call_args_list[1]
            assert call_args[0][0] == 'lambda'
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_with_tools_success(self, mock_sleep, mock_boto3):
        """Test successful investigation with tool calls using Converse API."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Converse API response with tool use
        converse_response_1 = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'TOOL: python_executor\n```python\nec2 = boto3.client("ec2")\nresult = ec2.describe_instances()\nprint(result)\n```'
                    }]
                }
            }
        }
        
        # Mock Converse API response with final text
        converse_response_2 = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'Investigation complete. Found permission issues.'
                    }]
                }
            }
        }
        
        mock_bedrock.converse.side_effect = [converse_response_1, converse_response_2]
        
        # Mock Lambda tool response
        mock_lambda.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'output': 'EC2 instances listed'
                })
            }).encode())
        }
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert result == 'Investigation complete. Found permission issues.'
        assert mock_bedrock.converse.call_count == 2
        assert mock_lambda.invoke.call_count == 1
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_with_multiple_tools(self, mock_sleep, mock_boto3):
        """Test investigation with multiple tool calls using Converse API."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock multiple Converse API responses with tool uses
        converse_responses = [
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'TOOL: python_executor\n```python\nec2 = boto3.client("ec2")\nresponse = ec2.describe_instances()\nprint(response)\n```'
                        }]
                    }
                }
            },
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'TOOL: python_executor\n```python\ncw = boto3.client("cloudwatch")\nalarms = cw.describe_alarms()\nprint(alarms)\n```'
                        }]
                    }
                }
            },
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Based on the investigation, the issue is with the EC2 instance state.'
                        }]
                    }
                }
            }
        ]
        
        mock_bedrock.converse.side_effect = converse_responses
        
        # Mock Lambda tool responses
        mock_lambda.invoke.side_effect = [
            {
                'StatusCode': 200,
                'Payload': Mock(read=lambda: json.dumps({
                    'statusCode': 200,
                    'body': json.dumps({
                        'success': True,
                        'output': 'EC2 instances: i-123456'
                    })
                }).encode())
            },
            {
                'StatusCode': 200,
                'Payload': Mock(read=lambda: json.dumps({
                    'statusCode': 200,
                    'body': json.dumps({
                        'success': True,
                        'output': 'Alarms found: CPUAlarm'
                    })
                }).encode())
            }
        ]
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert result == 'Based on the investigation, the issue is with the EC2 instance state.'
        assert mock_bedrock.converse.call_count == 3
        assert mock_lambda.invoke.call_count == 2
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_tool_error_handling(self, mock_sleep, mock_boto3):
        """Test error handling when tool execution fails."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Converse API response with tool use
        converse_response_1 = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'TOOL: python_executor\n```python\nec2 = boto3.client("ec2")\nresult = ec2.describe_instances()\n```'
                    }]
                }
            }
        }
        
        # Mock Converse API response after error
        converse_response_2 = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'Investigation failed due to tool execution error.'
                    }]
                }
            }
        }
        
        mock_bedrock.converse.side_effect = [converse_response_1, converse_response_2]
        
        # Mock Lambda tool error
        mock_lambda.invoke.return_value = {
            'StatusCode': 500,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'output': 'Internal server error'
                })
            }).encode())
        }
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert 'Investigation failed' in result
        assert mock_bedrock.converse.call_count == 2
        assert mock_lambda.invoke.call_count == 1
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_bedrock_error(self, mock_sleep, mock_boto3):
        """Test handling of Bedrock API errors."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock error
        mock_bedrock.converse.side_effect = Exception("Bedrock service error")
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert 'Investigation Error' in result
        assert 'Bedrock service error' in result
        assert mock_bedrock.converse.call_count == 1
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_max_iterations(self, mock_sleep, mock_boto3):
        """Test that investigation stops at max iterations."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Always return tool use (never ending investigation)
        converse_response = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'TOOL: python_executor\n```python\nprint("iteration")\n```'
                    }]
                }
            }
        }
        
        mock_bedrock.converse.return_value = converse_response
        
        # Mock Lambda tool response
        mock_lambda.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'output': 'Iteration output'
                })
            }).encode())
        }
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Should reach max_iterations (100)
        assert mock_bedrock.converse.call_count == 100
        assert mock_lambda.invoke.call_count == 100
        assert result == "Investigation completed but no analysis was generated."
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_unknown_tool(self, mock_sleep, mock_boto3):
        """Test handling of unknown tool in response."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Converse API response with invalid tool format
        converse_response_1 = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'TOOL: python_executor\nNo code block here'
                    }]
                }
            }
        }
        
        # Mock Converse API response after warning
        converse_response_2 = {
            'output': {
                'message': {
                    'content': [{
                        'text': 'Investigation complete without tool execution.'
                    }]
                }
            }
        }
        
        mock_bedrock.converse.side_effect = [converse_response_1, converse_response_2]
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert result == 'Investigation complete without tool execution.'
        assert mock_bedrock.converse.call_count == 2
        assert mock_lambda.invoke.call_count == 0  # No tool execution
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_investigate_empty_response(self, mock_sleep, mock_boto3):
        """Test handling of empty response from Bedrock."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock empty Converse API response
        converse_response = {
            'output': {
                'message': {
                    'content': [{
                        'text': ''
                    }]
                }
            }
        }
        
        mock_bedrock.converse.return_value = converse_response
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert result == "Investigation completed but no analysis was generated."
        assert mock_bedrock.converse.call_count == 1