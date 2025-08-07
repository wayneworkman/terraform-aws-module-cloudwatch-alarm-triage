import pytest
import json
from unittest.mock import Mock, patch, call
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from bedrock_client import BedrockAgentClient

class TestComplexInteractions:
    """Test complex multi-step interactions between Claude and tool Lambda."""
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')  # Speed up retry tests
    def test_claude_multi_tool_investigation_with_partial_failures(self, mock_sleep, mock_boto3_client):
        """Test Claude investigation with multiple tool calls where some fail."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock complex conversation: tool -> partial failure -> retry -> success
        bedrock_responses = [
            # First tool request
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-1',
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws logs describe-log-groups'}
                        }
                    ]
                }).encode())
            },
            # Second tool request after first fails
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-2',
                            'name': 'aws_investigator',
                            'input': {'type': 'python', 'command': 'import boto3; client = boto3.client("ec2"); result = "fallback"'}
                        }
                    ]
                }).encode())
            },
            # Third tool request 
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-3',
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws sts get-caller-identity'}
                        }
                    ]
                }).encode())
            },
            # Final response
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Investigation complete. Used multiple tools with some failures handled gracefully.'
                        }
                    ]
                }).encode())
            }
        ]
        
        mock_bedrock_client.invoke_model.side_effect = bedrock_responses
        
        # Mock Lambda responses: fail, fail, succeed
        lambda_responses = [
            # First call fails
            {
                'StatusCode': 200,
                'Payload': Mock(read=lambda: json.dumps({
                    'statusCode': 400,
                    'body': json.dumps({'success': False, 'output': 'Access denied to logs'})
                }).encode())
            },
            # Second call fails 
            {
                'StatusCode': 200,
                'Payload': Mock(read=lambda: json.dumps({
                    'statusCode': 500,
                    'body': json.dumps({'success': False, 'output': 'Python execution timeout'})
                }).encode())
            },
            # Third call succeeds
            {
                'StatusCode': 200,
                'Payload': Mock(read=lambda: json.dumps({
                    'statusCode': 200,
                    'body': json.dumps({'success': True, 'output': '{"Account": "123456789012"}'})
                }).encode())
            }
        ]
        
        mock_lambda_client.invoke.side_effect = lambda_responses
        
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Complex investigation prompt")
        
        # Should handle partial failures and complete investigation
        assert 'Investigation complete' in result
        assert 'multiple tools' in result
        
        # Verify all tool calls were attempted
        assert mock_lambda_client.invoke.call_count == 3
        assert mock_bedrock_client.invoke_model.call_count == 4
    
    @patch('bedrock_client.boto3.client')
    def test_claude_iterative_investigation_strategy(self, mock_boto3_client):
        """Test Claude building investigation iteratively based on previous results."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock iterative investigation pattern
        bedrock_responses = [
            # First: Check basic alarm info
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-1',
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws cloudwatch describe-alarms --alarm-names test-alarm'}
                        }
                    ]
                }).encode())
            },
            # Second: Based on alarm info, check logs
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-2', 
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': 'aws logs filter-log-events --log-group-name /aws/lambda/test-function --start-time 1234567890000'}
                        }
                    ]
                }).encode())
            },
            # Third: Based on logs, check IAM
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': 'tool-3',
                            'name': 'aws_investigator',
                            'input': {'type': 'python', 'command': 'import boto3; iam = boto3.client("iam"); result = "IAM check complete"'}
                        }
                    ]
                }).encode())
            },
            # Final analysis
            {
                'body': Mock(read=lambda: json.dumps({
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Root cause identified through iterative investigation: IAM permission issue in Lambda execution.'
                        }
                    ]
                }).encode())
            }
        ]
        
        mock_bedrock_client.invoke_model.side_effect = bedrock_responses
        
        # Mock successful Lambda responses
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Tool executed successfully'})
            }).encode())
        }
        
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Iterative investigation")
        
        # Should complete iterative investigation 
        assert 'Root cause identified through iterative investigation' in result
        assert 'IAM permission issue' in result
        
        # Verify iterative pattern
        assert mock_lambda_client.invoke.call_count == 3
        
        # Verify investigation progressed logically  
        call_commands = [call[1]['Payload'] for call in mock_lambda_client.invoke.call_args_list]
        
        # First call should be about alarms
        assert 'describe-alarms' in str(call_commands[0])
        # Second call should be about logs  
        assert 'filter-log-events' in str(call_commands[1])
        # Third call should be about IAM
        assert 'iam' in str(call_commands[2]).lower()
    
    @patch('bedrock_client.boto3.client')
    @patch('time.sleep')  # Mock sleep to speed up test
    def test_claude_max_iterations_with_persistent_tool_calls(self, mock_sleep, mock_boto3_client):
        """Test Claude handles persistent tool calls correctly."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Test with smaller number for speed - create 7 tool responses
        responses = []
        for i in range(7):
            response = {
                'body': Mock(read=lambda i=i: json.dumps({
                    'content': [
                        {
                            'type': 'tool_use',
                            'id': f'tool-{i}',
                            'name': 'aws_investigator',
                            'input': {'type': 'cli', 'command': f'aws ec2 describe-instances --instance-ids i-{i:08d}'}
                        }
                    ]
                }).encode())
            }
            responses.append(response)
        
        # Add final response with analysis
        responses.append({
            'body': Mock(read=lambda: json.dumps({
                'content': [
                    {
                        'type': 'text',
                        'text': 'Analysis complete: Found 7 instances with varying states.'
                    }
                ]
            }).encode())
        })
        
        mock_bedrock_client.invoke_model.side_effect = responses
        
        # Mock Lambda always returns new "interesting" information
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Found new instance data, investigating further...'})
            }).encode())
        }
        
        client = BedrockAgentClient('test-model', 'test-arn', 1000)
        result = client.investigate_with_tools("Deep investigation")
        
        # Should complete with analysis
        assert 'Analysis complete: Found 7 instances' in result
        
        # Should have made appropriate number of calls
        assert mock_bedrock_client.invoke_model.call_count == 8  # 7 tools + 1 final
        assert mock_lambda_client.invoke.call_count == 7  # 7 tool calls