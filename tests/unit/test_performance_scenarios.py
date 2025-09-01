import pytest
import json
from unittest.mock import Mock, patch
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from bedrock_client import BedrockAgentClient
from tool_handler import handler as tool_handler
from triage_handler import handler as triage_handler

class TestPerformanceScenarios:
    """Test performance and concurrent execution scenarios."""
    
    def test_tool_lambda_large_output_handling(self, mock_lambda_context):
        """Test tool Lambda handles very large command outputs gracefully."""
        # Test with large Python output
        event = {
            'type': 'python',
            'command': '''
# Generate large dataset
data = []
for i in range(10000):
    data.append({
        'id': i,
        'name': f'item_{i}',
        'description': f'This is a long description for item {i} ' * 10,
        'metadata': {'created': f'2025-01-{(i % 28) + 1:02d}', 'status': 'active'}
    })

result = json.dumps(data[:100])  # Return subset but create large intermediate data
'''
        }
        
        result = tool_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        
        # Should handle large intermediate processing without issues
        assert 'item_0' in body['output']
        assert len(body['output']) < 60000  # Should be truncated if too large
    
    def test_tool_lambda_memory_intensive_operations(self, mock_lambda_context):
        """Test tool Lambda with memory-intensive operations."""
        event = {
            'type': 'python',
            'command': '''
# Memory-intensive operation
large_dict = {}
for i in range(1000):
    large_dict[f'key_{i}'] = [j for j in range(100)]

# Process the data
processed = {k: len(v) for k, v in large_dict.items()}
result = f"Processed {len(processed)} keys, total items: {sum(processed.values())}"
'''
        }
        
        result = tool_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Processed 1000 keys' in body['output']
        assert 'total items: 100000' in body['output']
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_bedrock_client_with_many_rapid_tool_calls(self, mock_sleep, mock_boto3_client):
        """Test Bedrock client handling many rapid tool calls efficiently."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock rapid-fire tool usage (10 quick calls)
        bedrock_responses = []
        for i in range(10):
            bedrock_responses.append({
                'output': {
                    'message': {
                        'content': [{
                            'text': f'TOOL: python_executor\n```python\nec2 = boto3.client("ec2"); result = "instances-{i+1}"\n```'
                        }]
                    }
                }
            })
        
        # Final response
        bedrock_responses.append({
            'output': {
                    'message': {
                        'content': [{
                            'text': 'Rapid investigation completed using 10 quick tool calls.'
                        }]
                    }
                }
            })
        
        mock_bedrock_client.converse.side_effect = bedrock_responses
        
        # Mock fast Lambda responses
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Quick response'})
            }).encode())
        }
        
        start_time = time.time()
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Rapid investigation")
        end_time = time.time()
        
        # Should complete efficiently
        assert isinstance(result, dict) and 'Rapid investigation completed' in result.get("report", "")
        assert mock_lambda_client.invoke.call_count == 10
        
        # Should not take too long in testing (mocked, so should be very fast)
        assert end_time - start_time < 10.0  # More lenient timing for CI environments
    
    def test_concurrent_triage_handler_invocations(self, sample_alarm_event, mock_lambda_context):
        """Test multiple concurrent triage handler invocations."""
        
        def run_triage_handler(event_id):
            """Run triage handler with unique event."""
            test_event = sample_alarm_event.copy()
            test_event['alarmData'] = sample_alarm_event['alarmData'].copy()
            test_event['alarmData']['alarmName'] = f'test-alarm-{event_id}'
            
            # Need to patch environment variables for each thread
            with patch.dict(os.environ, {
                'BEDROCK_MODEL_ID': 'test-model',
                'TOOL_LAMBDA_ARN': 'test-arn',
                'SNS_TOPIC_ARN': 'test-topic',
                'DYNAMODB_TABLE': 'test-table',
                'INVESTIGATION_WINDOW_HOURS': '1'
            }):
                with patch('triage_handler.boto3.client') as mock_boto3:
                    with patch('triage_handler.boto3.resource') as mock_boto3_resource:
                        with patch('triage_handler.BedrockAgentClient') as mock_bedrock:
                            mock_bedrock.return_value.investigate_with_tools.return_value = f"Analysis for alarm {event_id}"
                            mock_sns = Mock()
                            mock_s3 = Mock()
                            
                            # Mock DynamoDB
                            mock_dynamodb_table = Mock()
                            mock_dynamodb_table.get_item.return_value = {}
                            mock_dynamodb_table.put_item.return_value = {}
                            mock_dynamodb_resource = Mock()
                            mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
                            mock_boto3_resource.return_value = mock_dynamodb_resource
                            
                            # Mock boto3.client to handle both SNS and S3
                            def client_factory(service_name, **kwargs):
                                if service_name == 'sns':
                                    return mock_sns
                                elif service_name == 's3':
                                    return mock_s3
                                return Mock()
                            mock_boto3.side_effect = client_factory
                            
                            result = triage_handler(test_event, mock_lambda_context)
                            return result
        
        # Run multiple handlers concurrently
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for i in range(5):
                future = executor.submit(run_triage_handler, i)
                futures.append(future)
            
            # Collect results
            results = []
            for future in futures:
                result = future.result()
                results.append(result)
        
        # All should succeed
        for result in results:
            assert result['statusCode'] == 200
            assert json.loads(result['body'])['investigation_complete'] is True
    
    def test_tool_lambda_command_timeout_handling(self, mock_lambda_context):
        """Test tool Lambda handling commands that approach timeout limits."""
        event = {
            'command': '''
import time
# Simulate long-running but legitimate operation
result_data = []
for i in range(50):
    # Small delay per iteration
    time.sleep(0.01)  # Total: 0.5 seconds  
    result_data.append(f'processed_item_{i}')

result = f"Completed processing {len(result_data)} items"
'''
        }
        
        # Mock sleep to avoid actual delays in test
        with patch('time.sleep'):
            result = tool_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Completed processing 50 items' in body['result'] or 'Completed processing 50 items' in body['output']
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_client_token_usage_efficiency(self, mock_boto3_client):
        """Test Bedrock client manages token usage efficiently."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Create client with low token limit to test efficiency
        client = BedrockAgentClient('test-model', 'test-arn')  # Very low token limit
        
        # Mock response that should fit in token limit
        mock_bedrock_client.converse.return_value = {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Brief analysis within token limits.'
                        }]
                    }
                }
            }
        
        result = client.investigate_with_tools("Brief investigation prompt")
        
        assert isinstance(result, dict) and 'Brief analysis within token limits' in result.get("report", "")
        
        # Verify that inferenceConfig is passed (no maxTokens anymore)
        call_args = mock_bedrock_client.converse.call_args
        inference_config = call_args[1]['inferenceConfig']
        assert 'temperature' in inference_config  # Only temperature is set now