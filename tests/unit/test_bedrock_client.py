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
                tool_lambda_arn='test-arn',
                max_tokens=1000
            )
            
            assert client.model_id == 'test-model'
            assert client.tool_lambda_arn == 'test-arn'
            assert client.max_tokens == 1000
            
            # Verify boto3 clients were created
            assert mock_boto3.call_count == 2
            # Check first call for bedrock-runtime
            call_args = mock_boto3.call_args_list[0]
            assert call_args[0][0] == 'bedrock-runtime'
            # Check second call for lambda
            call_args = mock_boto3.call_args_list[1]
            assert call_args[0][0] == 'lambda'
    
    @patch('bedrock_client.boto3.client')
    def test_investigate_with_tools_success(self, mock_boto3):
        """Test successful investigation with tool calls."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock response with tool use
        bedrock_response_1 = {
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
        
        # Mock Bedrock response with final text
        bedrock_response_2 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': 'Investigation complete. Found permission issues.'
                    }
                ]
            }).encode())
        }
        
        mock_bedrock.invoke_model.side_effect = [bedrock_response_1, bedrock_response_2]
        
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
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert result == 'Investigation complete. Found permission issues.'
        assert mock_bedrock.invoke_model.call_count == 2
        assert mock_lambda.invoke.call_count == 1
    
    @patch('bedrock_client.boto3.client')
    def test_investigate_with_multiple_tools(self, mock_boto3):
        """Test investigation with multiple tool calls."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock responses
        bedrock_response_1 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'tool-1',
                        'name': 'aws_investigator',
                        'input': {'type': 'cli', 'command': 'aws logs filter-log-events'}
                    },
                    {
                        'type': 'tool_use',
                        'id': 'tool-2',
                        'name': 'aws_investigator',
                        'input': {'type': 'python', 'command': 'import boto3\nresult = "test"'}
                    }
                ]
            }).encode())
        }
        
        bedrock_response_2 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': 'Analysis complete'
                    }
                ]
            }).encode())
        }
        
        mock_bedrock.invoke_model.side_effect = [bedrock_response_1, bedrock_response_2]
        
        # Mock Lambda responses
        mock_lambda.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Tool output'})
            }).encode())
        }
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Assertions
        assert result == 'Analysis complete'
        assert mock_lambda.invoke.call_count == 2  # Two tool calls
    
    @patch('bedrock_client.boto3.client')
    def test_investigate_tool_error_handling(self, mock_boto3):
        """Test handling of tool execution errors."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock response requesting tool
        bedrock_response_1 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'tool-1',
                        'name': 'aws_investigator',
                        'input': {'type': 'cli', 'command': 'aws s3 ls'}
                    }
                ]
            }).encode())
        }
        
        bedrock_response_2 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': 'Tool failed but continuing analysis'
                    }
                ]
            }).encode())
        }
        
        mock_bedrock.invoke_model.side_effect = [bedrock_response_1, bedrock_response_2]
        
        # Mock Lambda error
        mock_lambda.invoke.side_effect = Exception("Lambda invocation failed")
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should handle error and continue
        assert 'Tool failed but continuing analysis' in result
    
    @patch('bedrock_client.boto3.client')
    def test_investigate_bedrock_error(self, mock_boto3):
        """Test handling of Bedrock API errors."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock error
        mock_bedrock.invoke_model.side_effect = Exception("Bedrock API error")
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should return error message
        assert 'Investigation Error' in result
        assert 'Bedrock API error' in result
    
    @patch('bedrock_client.boto3.client')
    @patch('time.sleep')  # Mock sleep to speed up test
    def test_investigate_max_iterations(self, mock_sleep, mock_boto3):
        """Test that tool calls are limited to prevent infinite loops."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock to always request tools (simulate infinite loop)
        # But only create 5 responses for testing speed
        bedrock_responses = []
        for i in range(5):
            bedrock_responses.append({
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': f'tool-{i}',
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws ec2 describe-instances'}
                        }
                    ]
                }).encode())
            })
        
        # After 5 tool calls, return a final text response
        bedrock_responses.append({
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': 'Stopped after 5 iterations for testing'
                    }
                ]
            }).encode())
        })
        
        mock_bedrock.invoke_model.side_effect = bedrock_responses
        
        # Mock Lambda response
        mock_lambda.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Output'})
            }).encode())
        }
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should have made 6 bedrock calls (5 tool requests + 1 final response)
        assert mock_bedrock.invoke_model.call_count == 6
        # Should have made 5 lambda calls (one for each tool request)
        assert mock_lambda.invoke.call_count == 5
        # Result should contain the final text
        assert 'Stopped after 5 iterations' in result
    
    @patch('bedrock_client.boto3.client')
    def test_investigate_unknown_tool(self, mock_boto3):
        """Test handling of unknown tool requests."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Bedrock response with unknown tool
        bedrock_response_1 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'tool-1',
                        'name': 'unknown_tool',
                        'input': {'param': 'value'}
                    }
                ]
            }).encode())
        }
        
        bedrock_response_2 = {
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': 'Handled unknown tool'
                    }
                ]
            }).encode())
        }
        
        mock_bedrock.invoke_model.side_effect = [bedrock_response_1, bedrock_response_2]
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should handle unknown tool gracefully
        assert result == 'Handled unknown tool'
        # Lambda should not be invoked for unknown tool
        mock_lambda.invoke.assert_not_called()
    
    @patch('bedrock_client.boto3.client')
    def test_investigate_empty_response(self, mock_boto3):
        """Test handling of empty Claude response."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock empty Bedrock response
        bedrock_response = {
            'body': Mock(read=lambda: json.dumps({
                'content': []
            }).encode())
        }
        
        mock_bedrock.invoke_model.return_value = bedrock_response
        
        # Create client and run investigation
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Test prompt")
        
        # Should return default message
        assert 'Investigation completed but no analysis was generated' in result