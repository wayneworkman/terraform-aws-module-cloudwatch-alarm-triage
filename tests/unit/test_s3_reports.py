import pytest
import json
from unittest.mock import Mock, patch, MagicMock, call
import sys
import os
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from triage_handler import save_enhanced_reports_to_s3, format_notification, handler

class TestS3ReportSaving:
    """Test S3 report saving functionality."""
    
    @patch('triage_handler.boto3.client')
    def test_save_report_to_s3_success(self, mock_boto3_client):
        """Test successful saving of report to S3."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket', 'BEDROCK_MODEL_ID': 'test-model'}):
            with patch('triage_handler.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value.strftime.side_effect = [
                    '20240115_143025_UTC',  # timestamp
                    '2024/01/15'        # date path
                ]
                mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T14:30:25'
                
                # Create investigation result dict for new format
                investigation_result = {
                    'report': 'Test analysis content',
                    'full_context': [],
                    'iteration_count': 5,
                    'tool_calls': []
                }
                
                report_loc, context_loc, json_loc = save_enhanced_reports_to_s3(
                    alarm_name='test-alarm',
                    alarm_state='ALARM',
                    investigation_result=investigation_result,
                    event={'accountId': '123456789012', 'region': 'us-east-1'}
                )
                
                # Verify S3 client was created with correct region
                mock_boto3_client.assert_called_with('s3', region_name='us-east-1')
                
                # Verify put_object was called
                assert mock_s3.put_object.called
                call_args = mock_s3.put_object.call_args
                
                # Check bucket name
                assert call_args.kwargs['Bucket'] == 'test-bucket'
                
                # Check key format - now expecting timestamp first
                assert 'reports/2024/01/15/20240115_' in call_args.kwargs['Key']
                assert 'test-alarm' in call_args.kwargs['Key']
                
                # Should have 3 put_object calls (report.txt, context.txt, json)
                assert mock_s3.put_object.call_count == 3
                
                # Check return values
                assert report_loc.startswith('s3://test-bucket/reports/')
                assert context_loc.startswith('s3://test-bucket/reports/')
                assert json_loc.startswith('s3://test-bucket/reports/')
    
    def test_save_report_to_s3_no_bucket_configured(self):
        """Test behavior when REPORTS_BUCKET is not configured."""
        with patch.dict(os.environ, {}, clear=True):
            investigation_result = {'report': 'Test analysis', 'full_context': [], 'iteration_count': 0, 'tool_calls': []}
            report_loc, context_loc, json_loc = save_enhanced_reports_to_s3(
                alarm_name='test-alarm',
                alarm_state='ALARM',
                investigation_result=investigation_result,
                event={}
            )
            
            assert report_loc is None
            assert context_loc is None
            assert json_loc is None
    
    @patch('triage_handler.boto3.client')
    def test_save_report_to_s3_with_special_characters_in_alarm_name(self, mock_boto3_client):
        """Test saving report with special characters in alarm name."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket'}):
            with patch('triage_handler.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value.strftime.side_effect = [
                    '20240115-143025',
                    '2024/01/15'
                ]
                mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T14:30:25'
                
                investigation_result = {'report': 'Test analysis', 'full_context': [], 'iteration_count': 0, 'tool_calls': []}
                report_loc, context_loc, json_loc = save_enhanced_reports_to_s3(
                    alarm_name='test/alarm:with*special?chars',
                    alarm_state='ALARM',
                    investigation_result=investigation_result,
                    event={}
                )
                
                # Check that special characters were replaced
                call_args = mock_s3.put_object.call_args
                key = call_args.kwargs['Key']
                # Check that the filename part has special chars replaced
                filename = key.split('/')[-1]
                assert ':' not in filename
                assert '*' not in filename
                assert '?' not in filename
                assert 'test_alarm_with_special_chars' in filename
    
    @patch('triage_handler.boto3.client')
    def test_save_report_to_s3_error_handling(self, mock_boto3_client):
        """Test error handling when S3 operation fails."""
        mock_s3 = Mock()
        mock_s3.put_object.side_effect = Exception("S3 error")
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket'}):
            investigation_result = {'report': 'Test analysis', 'full_context': [], 'iteration_count': 0, 'tool_calls': []}
            report_loc, context_loc, json_loc = save_enhanced_reports_to_s3(
                alarm_name='test-alarm',
                alarm_state='ALARM',
                investigation_result=investigation_result,
                event={}
            )
            
            # Should return None on error
            assert report_loc is None
            assert context_loc is None
            assert json_loc is None
    
    @patch('triage_handler.boto3.client')
    def test_save_report_to_s3_with_custom_region(self, mock_boto3_client):
        """Test S3 saving with custom BEDROCK_REGION."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket', 'BEDROCK_REGION': 'eu-west-1'}):
            investigation_result = {'report': 'Test analysis', 'full_context': [], 'iteration_count': 0, 'tool_calls': []}
            save_enhanced_reports_to_s3(
                alarm_name='test-alarm',
                alarm_state='ALARM',
                investigation_result=investigation_result,
                event={}
            )
            
            # Verify S3 client was created with custom region
            mock_boto3_client.assert_called_with('s3', region_name='eu-west-1')
    
    def test_format_notification_without_s3_location(self):
        """Test notification formatting without S3 location."""
        result = format_notification(
            alarm_name='test-alarm',
            alarm_state='ALARM',
            analysis='Test analysis',
            event={'region': 'us-east-1', 'accountId': '123456789012'},
            report_location=None,
            context_location=None
        )
        
        assert 'CloudWatch Alarm Investigation Results' in result
        assert 'test-alarm' in result
        assert 'ALARM' in result
        assert 'Test analysis' in result
        assert 'Investigation Files:' not in result
    
    def test_format_notification_with_s3_location(self):
        """Test notification formatting with S3 location."""
        s3_location = 's3://test-bucket/reports/2024/01/15/test-alarm-20240115-143025.json'
        
        result = format_notification(
            alarm_name='test-alarm',
            alarm_state='ALARM',
            analysis='Test analysis',
            event={'region': 'us-east-1', 'accountId': '123456789012'},
            report_location=s3_location,
            context_location=None
        )
        
        assert 'CloudWatch Alarm Investigation Results' in result
        assert 'Investigation Files:' in result
        assert s3_location in result
        assert 'test-alarm' in result
        assert 'ALARM' in result
        assert 'Test analysis' in result
    
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
    @patch('triage_handler.save_enhanced_reports_to_s3')
    def test_handler_integration_with_s3_saving(self, mock_save_report, mock_boto3_client, 
                                                mock_bedrock_client, mock_should_investigate, 
                                                mock_lambda_context):
        """Test main handler integrates S3 saving correctly."""
        # Setup mocks
        mock_should_investigate.return_value = (True, 0)
        mock_bedrock_instance = Mock()
        mock_bedrock_instance.investigate_with_tools.return_value = {
            'report': 'Test analysis',
            'full_context': [],
            'iteration_count': 3,
            'tool_calls': []
        }
        mock_bedrock_client.return_value = mock_bedrock_instance
        
        mock_sns = Mock()
        mock_boto3_client.return_value = mock_sns
        
        mock_save_report.return_value = ('s3://test-bucket/reports/test_report.txt', 's3://test-bucket/reports/test_context.txt', 's3://test-bucket/reports/test.json')
        
        # Test event
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Call handler
        result = handler(event, mock_lambda_context)
        
        # Verify S3 saving was called with new format
        mock_save_report.assert_called_once()
        call_args = mock_save_report.call_args[0]
        assert call_args[0] == 'test-alarm'
        assert call_args[1] == 'ALARM'
        # The third argument should be the investigation result dict
        assert isinstance(call_args[2], dict) or isinstance(call_args[2], str)
        assert call_args[3] == event
        
        # Verify response includes S3 location
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['report_location'] == 's3://test-bucket/reports/test_report.txt'
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic',
        'DYNAMODB_TABLE': 'test-table'
        # Note: REPORTS_BUCKET is not set
    })
    @patch('triage_handler.should_investigate')
    @patch('triage_handler.BedrockAgentClient')
    @patch('triage_handler.boto3.client')
    @patch('triage_handler.save_enhanced_reports_to_s3')
    def test_handler_without_s3_bucket_configured(self, mock_save_report, mock_boto3_client,
                                                  mock_bedrock_client, mock_should_investigate,
                                                  mock_lambda_context):
        """Test handler works correctly when S3 bucket is not configured."""
        # Setup mocks
        mock_should_investigate.return_value = (True, 0)
        mock_bedrock_instance = Mock()
        mock_bedrock_instance.investigate_with_tools.return_value = {
            'report': 'Test analysis',
            'full_context': [],
            'iteration_count': 3,
            'tool_calls': []
        }
        mock_bedrock_client.return_value = mock_bedrock_instance
        
        mock_sns = Mock()
        mock_boto3_client.return_value = mock_sns
        
        mock_save_report.return_value = (None, None, None)  # No S3 locations
        
        # Test event
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Call handler
        result = handler(event, mock_lambda_context)
        
        # Verify S3 saving was still called
        mock_save_report.assert_called_once()
        
        # Verify response doesn't include S3 location
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'report_location' not in body
    
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
    @patch('triage_handler.save_enhanced_reports_to_s3')
    def test_handler_s3_saving_on_bedrock_error(self, mock_save_report, mock_boto3_client,
                                                mock_bedrock_client, mock_should_investigate,
                                                mock_lambda_context):
        """Test S3 saving still happens when Bedrock investigation fails."""
        # Setup mocks
        mock_should_investigate.return_value = (True, 0)
        mock_bedrock_instance = Mock()
        mock_bedrock_instance.investigate_with_tools.side_effect = Exception("Bedrock error")
        mock_bedrock_client.return_value = mock_bedrock_instance
        
        mock_sns = Mock()
        mock_boto3_client.return_value = mock_sns
        
        mock_save_report.return_value = ('s3://test-bucket/reports/error_report.txt', 's3://test-bucket/reports/error_context.txt', 's3://test-bucket/reports/error.json')
        
        # Test event
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Call handler
        result = handler(event, mock_lambda_context)
        
        # Verify S3 saving was called with error analysis
        mock_save_report.assert_called_once()
        call_args = mock_save_report.call_args[0]
        # The third argument is the investigation_result dict
        investigation_result = call_args[2]
        assert 'Investigation Error - Bedrock Unavailable' in investigation_result['report']
        
        # Verify response includes S3 location
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['report_location'] == 's3://test-bucket/reports/error_report.txt'
    
    @patch('triage_handler.boto3.client')
    def test_save_report_to_s3_comprehensive_report_structure(self, mock_boto3_client):
        """Test that saved report has all expected fields."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {
            'REPORTS_BUCKET': 'test-bucket',
            'BEDROCK_MODEL_ID': 'anthropic.claude-3',
            'BEDROCK_REGION': 'us-west-2'
        }):
            with patch('triage_handler.datetime') as mock_datetime:
                mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T14:30:25'
                mock_datetime.utcnow.return_value.strftime.side_effect = [
                    '20240115-143025',
                    '2024/01/15'
                ]
                
                event = {
                    'accountId': '123456789012',
                    'region': 'us-east-1',
                    'alarmData': {
                        'alarmName': 'CPU-High',
                        'state': {
                            'value': 'ALARM',
                            'reason': 'Threshold Crossed'
                        },
                        'configuration': {
                            'description': 'High CPU usage alarm'
                        }
                    }
                }
                
                investigation_result = {
                    'report': 'Detailed investigation results here',
                    'full_context': [],
                    'iteration_count': 10,
                    'tool_calls': []
                }
                save_enhanced_reports_to_s3(
                    alarm_name='CPU-High',
                    alarm_state='ALARM',
                    investigation_result=investigation_result,
                    event=event
                )
                
                # Should have been called 3 times (report.txt, context.txt, json)
                assert mock_s3.put_object.call_count == 3
                
                # Find the JSON call (it should be the third one)
                json_call = None
                for call in mock_s3.put_object.call_args_list:
                    if call.kwargs['Key'].endswith('.json'):
                        json_call = call
                        break
                
                assert json_call is not None
                report = json.loads(json_call.kwargs['Body'])
                
                # Verify report structure
                assert report['alarm_name'] == 'CPU-High'
                assert report['alarm_state'] == 'ALARM'
                assert report['investigation_timestamp'] == '2024-01-15T14:30:25'
                assert report['analysis'] == 'Detailed investigation results here'
                assert report['event'] == event
                assert report['iteration_count'] == 10
                
                # Verify metadata
                assert report['metadata']['bedrock_model'] == 'anthropic.claude-3'
                assert report['metadata']['region'] == 'us-west-2'
                assert report['metadata']['account_id'] == '123456789012'
    
    @patch('triage_handler.boto3.client')
    def test_save_report_to_s3_date_based_organization(self, mock_boto3_client):
        """Test that reports are organized by date in S3."""
        mock_s3 = Mock()
        mock_boto3_client.return_value = mock_s3
        
        with patch.dict(os.environ, {'REPORTS_BUCKET': 'test-bucket'}):
            # Test different dates
            test_cases = [
                ('2024/01/15', '20240115-100000'),
                ('2024/12/31', '20241231-235959'),
                ('2025/02/28', '20250228-120000')
            ]
            
            for date_path, timestamp in test_cases:
                with patch('triage_handler.datetime') as mock_datetime:
                    mock_datetime.utcnow.return_value.strftime.side_effect = [
                        timestamp,
                        date_path
                    ]
                    mock_datetime.utcnow.return_value.isoformat.return_value = '2024-01-15T00:00:00'
                    
                    investigation_result = {'report': 'Test', 'full_context': [], 'iteration_count': 0, 'tool_calls': []}
                    save_enhanced_reports_to_s3(
                        alarm_name='test-alarm',
                        alarm_state='ALARM',
                        investigation_result=investigation_result,
                        event={}
                    )
                    
                    call_args = mock_s3.put_object.call_args
                    key = call_args.kwargs['Key']
                    
                    # Verify date-based path
                    assert f'reports/{date_path}/' in key
                    assert timestamp in key