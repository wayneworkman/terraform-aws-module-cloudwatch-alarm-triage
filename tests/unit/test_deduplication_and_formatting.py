import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from datetime import datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from triage_handler import should_investigate, format_notification

class TestDeduplicationAndFormatting:
    """Test DynamoDB deduplication logic and notification formatting."""
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_should_investigate_first_alarm(self, mock_boto3_resource):
        """Test that first alarm occurrence triggers investigation."""
        # Mock DynamoDB table with no previous investigation
        mock_table = Mock()
        mock_table.get_item.return_value = {}  # No item found
        mock_table.put_item.return_value = {}
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # Should investigate when no previous investigation exists
        result, time_since = should_investigate('test-alarm', investigation_window_hours=1)
        
        assert result is True
        assert time_since == 0
        mock_table.get_item.assert_called_once_with(Key={'alarm_name': 'test-alarm'})
        mock_table.put_item.assert_called_once()
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_should_investigate_duplicate_within_window(self, mock_boto3_resource):
        """Test that duplicate alarms within window are skipped."""
        # Mock DynamoDB table with recent investigation
        mock_table = Mock()
        recent_time = int((datetime.now() - timedelta(minutes=30)).timestamp())
        mock_table.get_item.return_value = {
            'Item': {
                'alarm_name': 'test-alarm',
                'timestamp': Decimal(str(recent_time))  # Changed from 'last_investigated' to 'timestamp'
            }
        }
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # Should NOT investigate when recent investigation exists
        result, time_since = should_investigate('test-alarm', investigation_window_hours=1)
        
        assert result is False
        assert time_since > 0  # Should have time since last investigation
        mock_table.get_item.assert_called_once_with(Key={'alarm_name': 'test-alarm'})
        mock_table.put_item.assert_not_called()
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_should_investigate_after_window_expired(self, mock_boto3_resource):
        """Test that alarms after deduplication window trigger new investigation."""
        # Mock DynamoDB table with old investigation
        mock_table = Mock()
        old_time = int((datetime.now() - timedelta(hours=2)).timestamp())
        mock_table.get_item.return_value = {
            'Item': {
                'alarm_name': 'test-alarm',
                'timestamp': Decimal(str(old_time))  # Changed from 'last_investigated' to 'timestamp'
            }
        }
        mock_table.put_item.return_value = {}
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # Should investigate when previous investigation is old
        result, time_since = should_investigate('test-alarm', investigation_window_hours=1)
        
        assert result is True
        assert time_since == 0  # New investigation
        mock_table.get_item.assert_called_once_with(Key={'alarm_name': 'test-alarm'})
        mock_table.put_item.assert_called_once()
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_should_investigate_dynamodb_error_allows_investigation(self, mock_boto3_resource):
        """Test that DynamoDB errors don't block investigation."""
        # Mock DynamoDB table that throws error
        mock_table = Mock()
        mock_table.get_item.side_effect = Exception("DynamoDB unavailable")
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # Should still investigate when DynamoDB fails
        result, time_since = should_investigate('test-alarm', investigation_window_hours=1)
        
        assert result is True  # Fail open - investigate on error
        assert time_since == 0
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_should_investigate_custom_window(self, mock_boto3_resource):
        """Test custom investigation window configuration."""
        # Mock DynamoDB table with investigation just outside custom window
        mock_table = Mock()
        edge_time = int((datetime.now() - timedelta(hours=3, minutes=1)).timestamp())
        mock_table.get_item.return_value = {
            'Item': {
                'alarm_name': 'test-alarm',
                'timestamp': Decimal(str(edge_time))  # Changed from 'last_investigated' to 'timestamp'
            }
        }
        mock_table.put_item.return_value = {}
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # Should investigate with 3-hour window
        result, time_since = should_investigate('test-alarm', investigation_window_hours=3)
        
        assert result is True
        assert time_since == 0
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_should_investigate_ttl_expiry(self, mock_boto3_resource):
        """Test TTL field is set correctly for automatic cleanup."""
        mock_table = Mock()
        mock_table.get_item.return_value = {}  # No previous investigation
        mock_table.put_item.return_value = {}
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # Investigate and check TTL
        result, time_since = should_investigate('test-alarm', investigation_window_hours=2)
        
        assert result is True
        assert time_since == 0
        
        # Check that put_item was called with TTL
        put_call = mock_table.put_item.call_args
        item = put_call[1]['Item']
        
        assert 'ttl' in item
        assert 'timestamp' in item  # Changed from 'last_investigated' to 'timestamp'
        
        # TTL should be approximately 2 hours from now (matching investigation_window_hours)
        expected_ttl = int((datetime.now() + timedelta(hours=2)).timestamp())
        actual_ttl = int(item['ttl'])
        assert abs(expected_ttl - actual_ttl) < 60  # Within 1 minute tolerance
    
    def test_format_notification_complete_analysis(self):
        """Test formatting of complete investigation notification."""
        alarm_name = "high-cpu-alarm"
        alarm_state = "ALARM"
        analysis = """### 🚨 EXECUTIVE SUMMARY
EC2 instance experiencing high CPU utilization due to runaway process.

### 🔍 INVESTIGATION DETAILS
Found process consuming 95% CPU.

### 📊 ROOT CAUSE ANALYSIS
Application bug causing infinite loop.

### 🔧 IMMEDIATE ACTIONS
1. Restart the application
2. Apply hotfix

### 🛡️ PREVENTION MEASURES
Add CPU monitoring to CI/CD pipeline."""
        
        event = {
            'region': 'us-east-1',
            'accountId': '123456789012',
            'detail': {
                'alarmName': alarm_name,
                'state': {'value': alarm_state},
                'configuration': {
                    'metrics': [{
                        'namespace': 'AWS/EC2',
                        'name': 'CPUUtilization'
                    }]
                }
            }
        }
        
        result = format_notification(alarm_name, alarm_state, analysis, event)
        
        # Check structure - updated to match actual output format
        assert "CloudWatch Alarm Investigation Results" in result
        assert f"Alarm: {alarm_name}" in result
        assert f"State: {alarm_state}" in result
        assert "Region: us-east-1" in result
        assert "Account: 123456789012" in result
        assert "EXECUTIVE SUMMARY" in result
        assert "INVESTIGATION DETAILS" in result
        assert "ROOT CAUSE ANALYSIS" in result
        assert "IMMEDIATE ACTIONS" in result
        assert "PREVENTION MEASURES" in result
    
    def test_format_notification_minimal_analysis(self):
        """Test formatting with minimal analysis content."""
        alarm_name = "test-alarm"
        alarm_state = "OK"
        analysis = "Simple analysis: Alarm has recovered."
        
        event = {
            'detail': {
                'alarmName': alarm_name,
                'state': {'value': alarm_state}
            }
        }
        
        result = format_notification(alarm_name, alarm_state, analysis, event)
        
        assert "CloudWatch Alarm Investigation Results" in result
        assert f"Alarm: {alarm_name}" in result
        assert f"State: {alarm_state}" in result
        assert "Simple analysis: Alarm has recovered." in result
    
    def test_format_notification_missing_metrics(self):
        """Test formatting when metric information is missing."""
        alarm_name = "custom-alarm"
        alarm_state = "ALARM"
        analysis = "Investigation complete."
        
        event = {
            'detail': {
                'alarmName': alarm_name,
                'state': {'value': alarm_state}
            }
        }
        
        result = format_notification(alarm_name, alarm_state, analysis, event)
        
        assert "CloudWatch Alarm Investigation Results" in result
        assert f"Alarm: {alarm_name}" in result
        assert f"State: {alarm_state}" in result
        assert "Region:" in result
        assert "Account:" in result
    
    def test_format_notification_multiple_metrics(self):
        """Test formatting with composite alarm having multiple metrics."""
        alarm_name = "composite-alarm"
        alarm_state = "ALARM"
        analysis = "Multiple metrics breached."
        
        event = {
            'detail': {
                'alarmName': alarm_name,
                'state': {'value': alarm_state},
                'configuration': {
                    'metrics': [
                        {
                            'namespace': 'AWS/Lambda',
                            'name': 'Errors'
                        },
                        {
                            'namespace': 'AWS/Lambda',
                            'name': 'Duration'
                        }
                    ]
                }
            }
        }
        
        result = format_notification(alarm_name, alarm_state, analysis, event)
        
        assert "CloudWatch Alarm Investigation Results" in result
        assert f"Alarm: {alarm_name}" in result
        assert f"State: {alarm_state}" in result
        assert "Multiple metrics breached" in result
    
    def test_format_notification_with_special_characters(self):
        """Test formatting handles special characters in analysis."""
        alarm_name = "test-alarm"
        alarm_state = "ALARM"
        analysis = """### Analysis with special chars
        
Contains: <tags>, "quotes", 'apostrophes', & ampersands
URLs: https://example.com/path?param=value&other=123
Code: `lambda x: x**2`
JSON: {"key": "value", "number": 123}"""
        
        event = {
            'detail': {
                'alarmName': alarm_name,
                'state': {'value': alarm_state}
            }
        }
        
        result = format_notification(alarm_name, alarm_state, analysis, event)
        
        # All content should be preserved
        assert "<tags>" in result
        assert '"quotes"' in result
        assert "'apostrophes'" in result
        assert "& ampersands" in result
        assert "https://example.com/path?param=value&other=123" in result
        assert "`lambda x: x**2`" in result
        assert '{"key": "value", "number": 123}' in result
    
    def test_format_notification_very_long_analysis(self):
        """Test formatting handles very long analysis text."""
        alarm_name = "test-alarm"
        alarm_state = "ALARM"
        
        # Create very long analysis
        long_section = "Very detailed finding. " * 100
        analysis = f"""### 🚨 EXECUTIVE SUMMARY
{long_section}

### 🔍 INVESTIGATION DETAILS
{long_section}

### 📊 ROOT CAUSE ANALYSIS
{long_section}"""
        
        event = {
            'region': 'us-east-2',
            'detail': {
                'alarmName': alarm_name,
                'state': {'value': alarm_state}
            }
        }
        
        result = format_notification(alarm_name, alarm_state, analysis, event)
        
        # Should include all content (no truncation in format_notification)
        assert len(result) > 5000  # Adjusted expectation - header/footer adds ~500 chars
        assert "Very detailed finding" in result
    
    @patch.dict(os.environ, {'DYNAMODB_TABLE': 'test-table'})
    @patch('triage_handler.boto3.resource')
    def test_concurrent_deduplication_handling(self, mock_boto3_resource):
        """Test that concurrent alarm checks handle deduplication correctly."""
        # Mock DynamoDB table for concurrent access
        mock_table = Mock()
        
        # First call returns no item, second call returns item (simulating race)
        mock_table.get_item.side_effect = [
            {},  # First check - no item
            {'Item': {'alarm_name': 'test-alarm', 'timestamp': Decimal(str(int(datetime.now().timestamp())))}}  # Second check - item exists
        ]
        
        mock_table.put_item.return_value = {}
        
        mock_dynamodb = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_dynamodb
        
        # First call should investigate
        result1, time1 = should_investigate('test-alarm', investigation_window_hours=1)
        assert result1 is True
        assert time1 == 0
        
        # Second call should not investigate (item now exists)
        result2, time2 = should_investigate('test-alarm', investigation_window_hours=1)
        assert result2 is False
        assert time2 > 0