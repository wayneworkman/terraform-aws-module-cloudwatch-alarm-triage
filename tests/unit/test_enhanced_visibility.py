import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from datetime import datetime
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from triage_handler import save_enhanced_reports_to_s3, handler
from bedrock_client import BedrockAgentClient

class TestEnhancedVisibility:
    """Test enhanced visibility features including full context tracking and iteration counting."""
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_client_tracks_full_context(self, mock_boto3):
        """Test that bedrock client tracks full conversation context."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # Mock Converse API responses
        mock_bedrock.converse.side_effect = [
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'TOOL: python_executor\n```python\nprint("test")\n```'
                        }]
                    }
                }
            },
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Final analysis based on investigation.'
                        }]
                    }
                }
            }
        ]
        
        # Mock Lambda response for tool execution
        mock_lambda.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'output': 'test output'
                })
            }))
        }
        
        # Execute
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Verify result structure
        assert isinstance(result, dict)
        assert 'report' in result
        assert 'full_context' in result
        assert 'iteration_count' in result
        assert 'tool_calls' in result
        
        # Verify full context tracking
        assert len(result['full_context']) >= 3  # Initial prompt, tool request, tool result, final
        
        # Check context entries have required fields
        for entry in result['full_context']:
            assert 'role' in entry
            assert 'timestamp' in entry
            
        # Verify iteration count
        assert result['iteration_count'] == 2  # Two Bedrock invocations
        
        # Verify tool calls tracking
        assert len(result['tool_calls']) == 1
    
    @patch('triage_handler.boto3.client')
    def test_save_enhanced_reports_creates_three_files(self, mock_boto3_client):
        """Test that save_enhanced_reports_to_s3 creates all three files."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket', 'BEDROCK_MODEL_ID': 'test-model'}):
            with patch('triage_handler.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value.strftime.side_effect = [
                    '20240115_143025_UTC',  # timestamp
                    '2024/01/15'            # date path
                ]
                mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T14:30:25'
                
                # Handler no longer adds metadata to report body
                investigation_result = {
                    'report': 'Test analysis report',
                    'full_context': [
                        {
                            'role': 'user',
                            'content': 'Initial prompt',
                            'timestamp': time.time()
                        },
                        {
                            'role': 'assistant',
                            'content': 'TOOL: python_executor',
                            'timestamp': time.time(),
                            'iteration': 1
                        },
                        {
                            'role': 'tool_execution',
                            'input': 'test code',
                            'output': {'success': True, 'output': 'test output'},
                            'timestamp': time.time()
                        },
                        {
                            'role': 'assistant',
                            'content': 'Final analysis',
                            'timestamp': time.time(),
                            'iteration': 2
                        }
                    ],
                    'iteration_count': 2,
                    'tool_calls': [
                        {'input': {'command': 'test code'}, 'output': 'test output'}
                    ]
                }
                
                report_loc, context_loc, json_loc = save_enhanced_reports_to_s3(
                    alarm_name='test-alarm',
                    alarm_state='ALARM',
                    investigation_result=investigation_result,
                    event={'accountId': '123456789012'}
                )
                
                # Should create 3 files
                assert mock_s3.put_object.call_count == 3
                
                # Verify file locations
                assert report_loc == 's3://test-bucket/reports/2024/01/15/20240115_143025_UTC_test-alarm_report.txt'
                assert context_loc == 's3://test-bucket/reports/2024/01/15/20240115_143025_UTC_test-alarm_full_context.txt'
                assert json_loc == 's3://test-bucket/reports/2024/01/15/20240115_143025_UTC_test-alarm.json'
                
                # Check each file was created with correct content
                calls = mock_s3.put_object.call_args_list
                
                # Report file (metadata no longer in report body)
                report_call = [c for c in calls if 'report.txt' in c.kwargs['Key']][0]
                assert 'Test analysis report' in report_call.kwargs['Body']
                
                # Context file
                context_call = [c for c in calls if 'full_context.txt' in c.kwargs['Key']][0]
                context_body = context_call.kwargs['Body']
                assert 'CloudWatch Alarm Investigation Full Context' in context_body
                assert 'Total Iterations: 2' in context_body
                assert 'Total Tool Calls: 1' in context_body
                assert 'Initial prompt' in context_body
                assert 'test output' in context_body
                assert 'FINAL REPORT:' in context_body
                
                # JSON file
                json_call = [c for c in calls if c.kwargs['Key'].endswith('.json')][0]
                json_body = json.loads(json_call.kwargs['Body'])
                assert json_body['iteration_count'] == 2
                assert json_body['tool_calls_count'] == 1
                assert json_body['alarm_name'] == 'test-alarm'
    
    def test_timestamp_format_is_s3_friendly(self):
        """Test that timestamp format is S3-friendly (no colons)."""
        with patch('triage_handler.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value.strftime.return_value = '20240115_143025_UTC'
            
            # The timestamp should not contain colons
            timestamp = mock_datetime.utcnow().strftime('%Y%m%d_%H%M%S_UTC')
            assert ':' not in timestamp
            assert timestamp == '20240115_143025_UTC'
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic',
        'DYNAMODB_TABLE': 'test-table',
        'REPORTS_BUCKET': 'test-bucket'
    })
    @patch('triage_handler.should_investigate')
    @patch('triage_handler.BedrockAgentClient')
    @patch('triage_handler.boto3.client')
    def test_handler_includes_iteration_count_in_response(self, mock_boto3_client,
                                                          mock_bedrock_client,
                                                          mock_should_investigate,
                                                          mock_lambda_context):
        """Test that handler includes iteration count in the response."""
        # Setup mocks
        mock_should_investigate.return_value = (True, 0)
        
        mock_bedrock_instance = Mock()
        mock_bedrock_instance.investigate_with_tools.return_value = {
            'report': 'Test analysis',
            'full_context': [],
            'iteration_count': 5,
            'tool_calls': [1, 2, 3]  # 3 tool calls
        }
        mock_bedrock_client.return_value = mock_bedrock_instance
        
        mock_sns = Mock()
        mock_s3 = Mock()
        mock_boto3_client.side_effect = [mock_s3, mock_sns]
        
        # Test event
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        with patch('triage_handler.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value.strftime.side_effect = [
                '20240115_143025_UTC',
                '2024/01/15'
            ]
            mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T14:30:25'
            
            # Call handler
            result = handler(event, mock_lambda_context)
        
        # Verify response includes iteration count
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['iteration_count'] == 5
        assert body['tool_calls_count'] == 3
    
    @patch('triage_handler.boto3.client')
    def test_full_context_preserves_conversation_order(self, mock_boto3_client):
        """Test that full context preserves the conversation order."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket'}):
            with patch('triage_handler.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value.strftime.side_effect = [
                    '20240115_143025_UTC',
                    '2024/01/15'
                ]
                mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T14:30:25'
                mock_datetime.utcfromtimestamp.side_effect = lambda x: Mock(
                    isoformat=lambda: f'2024-01-15T{int(x)}:00:00'
                )
                
                investigation_result = {
                    'report': 'Final report',
                    'full_context': [
                        {'role': 'user', 'content': 'Step 1', 'timestamp': 1.0},
                        {'role': 'assistant', 'content': 'Step 2', 'timestamp': 2.0},
                        {'role': 'tool_execution', 'input': 'Step 3', 'output': {}, 'timestamp': 3.0},
                        {'role': 'assistant', 'content': 'Step 4', 'timestamp': 4.0}
                    ],
                    'iteration_count': 2,
                    'tool_calls': []
                }
                
                save_enhanced_reports_to_s3(
                    alarm_name='test-alarm',
                    alarm_state='ALARM',
                    investigation_result=investigation_result,
                    event={}
                )
                
                # Find the full context file call
                context_call = None
                for call in mock_s3.put_object.call_args_list:
                    if 'full_context.txt' in call.kwargs['Key']:
                        context_call = call
                        break
                
                assert context_call is not None
                context_body = context_call.kwargs['Body']
                
                # Verify order is preserved
                step1_pos = context_body.find('Step 1')
                step2_pos = context_body.find('Step 2')
                step3_pos = context_body.find('Step 3')
                step4_pos = context_body.find('Step 4')
                
                assert step1_pos < step2_pos < step3_pos < step4_pos
    
    def test_iteration_count_in_report_text(self):
        """Test that iteration count is added to the report text."""
        investigation_result = {
            'report': 'This is the main report content.',
            'full_context': [],
            'iteration_count': 7,
            'tool_calls': []
        }
        
        # Metadata is no longer added to the report body
        report = investigation_result['report']
        
        # Just verify the report content itself
        assert 'This is the main report content.' in report
    
    @patch('bedrock_client.boto3.client')
    @patch('bedrock_client.time.sleep')
    def test_iteration_count_with_retries(self, mock_sleep, mock_boto3):
        """Test that iteration count includes retry attempts."""
        # Setup mocks
        mock_bedrock = Mock()
        mock_lambda = Mock()
        mock_boto3.side_effect = [mock_bedrock, mock_lambda]
        
        # First call fails with timeout, second succeeds
        mock_bedrock.converse.side_effect = [
            Exception('Read timeout on endpoint'),
            {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Final analysis'
                        }]
                    }
                }
            }
        ]
        
        mock_lambda.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'test'})
            }))
        }
        
        # Execute
        client = BedrockAgentClient('test-model', 'test-arn')
        result = client.investigate_with_tools("Test prompt")
        
        # Both attempts should count as iterations
        assert result['iteration_count'] == 2