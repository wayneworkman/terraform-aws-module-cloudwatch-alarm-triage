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
                'output': {
                        'message': {
                            'content': [{
                                'text': 'TOOL: python_executor\n```python\nlogs = boto3.client(\"logs\"); result = logs.describe_log_groups()\n```'
                            }]
                        }
                    }
            },
            # Second tool request after first fails
            {
                'output': {
                        'message': {
                            'content': [{
                                'text': 'TOOL: python_executor\n```python\nclient = boto3.client(\"ec2\"); result = \"fallback\"\n```'
                            }]
                        }
                    }
            },
            # Third tool request 
            {
                'output': {
                        'message': {
                            'content': [{
                                'text': 'TOOL: python_executor\n```python\nsts = boto3.client(\"sts\"); result = sts.get_caller_identity()\n```'
                            }]
                        }
                    }
            },
            # Final response
            {
                'output': {
                        'message': {
                            'content': [{
                                'text': 'Investigation complete. Used multiple tools with some failures handled gracefully.'
                            }]
                        }
                    }
                }
        ]
        
        mock_bedrock_client.converse.side_effect = bedrock_responses
        
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
        
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Complex investigation prompt")
        
        # Should handle partial failures and complete investigation
        assert isinstance(result, dict) and 'Investigation complete' in result.get("report", "")
        assert isinstance(result, dict) and 'multiple tools' in result.get("report", "")
        
        # Verify all tool calls were attempted
        assert mock_lambda_client.invoke.call_count == 3
        assert mock_bedrock_client.converse.call_count == 4
    
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
                'output': {
                        'message': {
                            'content': [{
                                'text': 'TOOL: python_executor\n```python\ncw = boto3.client(\"cloudwatch\"); result = cw.describe_alarms(AlarmNames=[\"test-alarm\"])\n```'
                            }]
                        }
                    }
            },
            # Second: Based on alarm info, check logs
            {
                'output': {
                        'message': {
                            'content': [{
                                'text': 'TOOL: python_executor\n```python\nlogs = boto3.client(\"logs\"); result = logs.filter_log_events(logGroupName=\"/aws/lambda/test-function\", startTime=1234567890000)\n```'
                            }]
                        }
                    }
            },
            # Third: Based on logs, check IAM
            {
                'output': {
                        'message': {
                            'content': [{
                                'text': 'TOOL: python_executor\n```python\niam = boto3.client(\"iam\"); result = \"IAM check complete\"\n```'
                            }]
                        }
                    }
            },
            # Final analysis
            {
                'output': {
                        'message': {
                            'content': [{
                                'text': 'Root cause identified through iterative investigation: IAM permission issue in Lambda execution.'
                            }]
                        }
                    }
                }
        ]
        
        mock_bedrock_client.converse.side_effect = bedrock_responses
        
        # Mock successful Lambda responses
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Tool executed successfully'})
            }).encode())
        }
        
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Iterative investigation")
        
        # Should complete iterative investigation 
        assert isinstance(result, dict) and 'Root cause identified through iterative investigation' in result.get("report", "")
        assert isinstance(result, dict) and 'IAM permission issue' in result.get("report", "")
        
        # Verify iterative pattern
        assert mock_lambda_client.invoke.call_count == 3
        
        # Verify investigation progressed logically  
        call_commands = [call[1]['Payload'] for call in mock_lambda_client.invoke.call_args_list]
        
        # First call should be about alarms
        assert 'describe_alarms' in str(call_commands[0])
        # Second call should be about logs  
        assert 'filter_log_events' in str(call_commands[1])
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
                'output': {
                    'message': {
                        'content': [{
                            'text': f'TOOL: python_executor\n```python\nec2 = boto3.client("ec2"); result = ec2.describe_instances(InstanceIds=["i-{i:08d}"])\n```'
                        }]
                    }
                }
            }
            responses.append(response)
        
        # Add final response with analysis
        responses.append({
            'output': {
                    'message': {
                        'content': [{
                            'text': 'Analysis complete: Found 7 instances with varying states.'
                        }]
                    }
                }
            })
        
        mock_bedrock_client.converse.side_effect = responses
        
        # Mock Lambda always returns new "interesting" information
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Found new instance data, investigating further...'})
            }).encode())
        }
        
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Deep investigation")
        
        # Should complete with analysis
        assert isinstance(result, dict) and 'Analysis complete: Found 7 instances' in result.get("report", "")
        
        # Should have made appropriate number of calls
        assert mock_bedrock_client.converse.call_count == 8  # 7 tools + 1 final
        assert mock_lambda_client.invoke.call_count == 7  # 7 tool calls