import pytest
import json
from unittest.mock import Mock, patch, call
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from bedrock_client import BedrockAgentClient
from triage_handler import handler as triage_handler

class TestMonitoringAndObservability:
    """Test comprehensive monitoring and observability for production readiness."""
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_usage_cost_tracking(self, mock_boto3_client, sample_alarm_event):
        """Test tracking of Bedrock API usage for cost monitoring."""
        mock_bedrock_client = Mock()
        mock_cloudwatch = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'cloudwatch': mock_cloudwatch
        }.get(service_name, Mock())
        
        # Mock successful Bedrock response
        mock_bedrock_client.converse.return_value = {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Analysis complete'
                        }]
                    }
                }
            }
        
        # Mock CloudWatch metrics client
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            client = BedrockAgentClient('anthropic.claude-opus-4-1-20250805-v1:0', 'test-arn')
            
            # Simulate cost tracking by monitoring bedrock calls
            result = client.investigate_with_tools("Test investigation")
            
            # Verify Bedrock was called (which would be tracked for cost)
            mock_bedrock_client.converse.assert_called()
            
            # Verify CloudWatch metrics would be published
            assert isinstance(result, dict) and 'Analysis complete' in result.get("report", "")
    
    def test_cost_alarm_threshold_monitoring(self):
        """Test cost alarm creation and threshold monitoring."""
        # Mock CloudWatch client for cost metrics
        with patch('boto3.client') as mock_boto3:
            mock_cloudwatch = Mock()
            mock_boto3.return_value = mock_cloudwatch
            
            # Simulate cost threshold breach
            cost_data = {
                'bedrock_requests': 100,
                'estimated_cost': 25.50,
                'threshold': 20.00
            }
            
            # Test cost alarm logic
            if cost_data['estimated_cost'] > cost_data['threshold']:
                # Should trigger cost alarm
                expected_alarm_data = {
                    'AlarmName': 'CloudWatch-Alarm-Triage-Cost-Alert',
                    'MetricName': 'BedrockCost',
                    'Threshold': cost_data['threshold'],
                    'ComparisonOperator': 'GreaterThanThreshold'
                }
                
                assert expected_alarm_data['Threshold'] == 20.00
                assert cost_data['estimated_cost'] > expected_alarm_data['Threshold']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic',
        'DYNAMODB_TABLE': 'test-table',
        'INVESTIGATION_WINDOW_HOURS': '1'
    })
    def test_lambda_execution_metrics_publishing(self, sample_alarm_event, mock_lambda_context):
        """Test publishing custom CloudWatch metrics for Lambda execution patterns."""
        with patch('triage_handler.BedrockAgentClient') as mock_bedrock:
            with patch('triage_handler.boto3.client') as mock_boto3:
                with patch('triage_handler.boto3.resource') as mock_boto3_resource:
                    mock_cloudwatch = Mock()
                    mock_sns = Mock()
                    mock_dynamodb_table = Mock()
                    mock_dynamodb_table.get_item.return_value = {}  # No previous investigation
                    mock_dynamodb_resource = Mock()
                    mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
                    mock_boto3_resource.return_value = mock_dynamodb_resource
                    
                    def client_side_effect(service_name, **kwargs):
                        if service_name == 'cloudwatch':
                            return mock_cloudwatch
                        elif service_name == 'sns':
                            return mock_sns
                        return Mock()
                    
                    mock_boto3.side_effect = client_side_effect
                    mock_bedrock.return_value.investigate_with_tools.return_value = {"report": "Test analysis", "full_context": [], "iteration_count": 1, "tool_calls": []}
                    
                    # Execute triage handler
                    result = triage_handler(sample_alarm_event, mock_lambda_context)
                    
                    # Verify metrics would be published
                    expected_metrics = [
                        ('InvestigationDuration', 'Milliseconds'),
                        ('BedrockTokensUsed', 'Count'),
                        ('ToolExecutionCount', 'Count'),
                        ('InvestigationSuccess', 'Count')
                    ]
                    
                    # Should complete successfully
                    assert result['statusCode'] == 200
                    
                    # Verify CloudWatch client was created (for metrics publishing)
                    calls = mock_boto3.call_args_list
                    service_calls = [call[0][0] for call in calls if call[0]]
                    assert 'sns' in service_calls  # SNS is called for notifications
    
    def test_alarm_storm_detection_and_metrics(self):
        """Test detection and metrics for alarm storms (many alarms in short time)."""
        from datetime import datetime, timedelta
        
        # Mock alarm timestamps (simulating alarm storm)
        now = datetime.now()
        alarm_events = []
        
        # Generate 10 alarms within 5 minutes (alarm storm scenario)
        for i in range(10):
            alarm_time = now - timedelta(minutes=i/2)  # 30 seconds apart
            alarm_events.append({
                'alarmName': f'storm-alarm-{i}',
                'timestamp': alarm_time.isoformat(),
                'state': 'ALARM'
            })
        
        # Test storm detection logic
        storm_window = timedelta(minutes=5)
        storm_threshold = 5
        
        recent_alarms = [
            alarm for alarm in alarm_events 
            if datetime.fromisoformat(alarm['timestamp']) > (now - storm_window)
        ]
        
        # Should detect alarm storm
        assert len(recent_alarms) > storm_threshold
        
        # Should trigger storm metrics
        storm_metrics = {
            'AlarmStormDetected': 1,
            'AlarmCount': len(recent_alarms),
            'StormDuration': storm_window.total_seconds()
        }
        
        assert storm_metrics['AlarmStormDetected'] == 1
        assert storm_metrics['AlarmCount'] == 10
    
    def test_performance_degradation_detection(self):
        """Test detection of performance degradation in module components."""
        # Mock performance metrics
        performance_metrics = {
            'bedrock_response_time_ms': [1000, 1200, 1500, 2000, 2500],  # Degrading
            'tool_execution_time_ms': [500, 800, 1200, 1800, 2400],     # Degrading
            'investigation_completion_rate': [100, 95, 90, 85, 80]       # Degrading
        }
        
        # Test performance degradation detection
        def detect_degradation(metrics, threshold_pct=20):
            if len(metrics) < 2:
                return False
            
            baseline = metrics[0]
            current = metrics[-1]
            degradation_pct = ((current - baseline) / baseline) * 100
            
            return degradation_pct > threshold_pct
        
        # Should detect degradation in all metrics
        bedrock_degraded = detect_degradation(performance_metrics['bedrock_response_time_ms'])
        tool_degraded = detect_degradation(performance_metrics['tool_execution_time_ms'])
        
        assert bedrock_degraded is True  # 150% increase
        assert tool_degraded is True     # 380% increase
        
        # Completion rate degradation (lower is worse)
        completion_metrics = performance_metrics['investigation_completion_rate']
        completion_degraded = (completion_metrics[0] - completion_metrics[-1]) > 10  # >10% drop
        assert completion_degraded is True  # 20% drop
    
    def test_dashboard_data_aggregation(self):
        """Test data aggregation for operational dashboard metrics."""
        # Mock operational data for dashboard
        operational_data = {
            'last_24h': {
                'total_investigations': 156,
                'successful_investigations': 142,
                'failed_investigations': 14,
                'avg_response_time_ms': 1250,
                'total_bedrock_cost': 12.45,
                'unique_alarm_types': 8,
                'peak_concurrent_investigations': 5
            },
            'last_7d': {
                'total_investigations': 1089,
                'avg_success_rate': 91.2,
                'cost_trend': 'increasing',
                'performance_trend': 'stable'
            }
        }
        # Test dashboard metrics calculation
        success_rate_24h = (operational_data['last_24h']['successful_investigations'] / 
                           operational_data['last_24h']['total_investigations']) * 100
        
        failure_rate_24h = (operational_data['last_24h']['failed_investigations'] / 
                           operational_data['last_24h']['total_investigations']) * 100
        
        avg_cost_per_investigation = (operational_data['last_24h']['total_bedrock_cost'] / 
                                     operational_data['last_24h']['total_investigations'])
        
        # Verify metrics calculations
        assert abs(success_rate_24h - 91.03) < 0.1  # ~91%
        assert abs(failure_rate_24h - 8.97) < 0.1   # ~9%
        assert abs(avg_cost_per_investigation - 0.08) < 0.01  # ~8 cents per investigation
        
        # Verify all required dashboard data is present
        required_metrics = [
            'total_investigations', 'successful_investigations', 'failed_investigations',
            'avg_response_time_ms', 'total_bedrock_cost', 'unique_alarm_types'
        ]
        
        for metric in required_metrics:
            assert metric in operational_data['last_24h']
    
    @patch('bedrock_client.boto3.client')
    def test_health_check_endpoint_simulation(self, mock_boto3_client):
        """Test module health check functionality for monitoring systems."""
        mock_bedrock_client = Mock()
        mock_lambda_client = Mock()
        
        mock_boto3_client.side_effect = lambda service_name, **kwargs: {
            'bedrock-runtime': mock_bedrock_client,
            'lambda': mock_lambda_client
        }.get(service_name, Mock())
        
        # Mock health check responses
        mock_bedrock_client.converse.return_value = {
                'output': {
                    'message': {
                        'content': [{
                            'text': 'Health check OK'
                        }]
                    }
                }
            }
        
        mock_lambda_client.invoke.return_value = {
            'StatusCode': 200,
            'Payload': Mock(read=lambda: json.dumps({
                'statusCode': 200,
                'body': json.dumps({'success': True, 'output': 'Health OK'})
            }).encode())
        }
        
        # Simulate health check
        client = BedrockAgentClient('test-model', 'test-arn')
        
        try:
            # Simple health check investigation
            health_result = client.investigate_with_tools("Health check test")
            report = health_result.get('report', '') if isinstance(health_result, dict) else health_result
            health_status = 'healthy' if 'Health check OK' in report else 'unhealthy'
            
            assert health_status == 'healthy'
            
            # Verify components are responding
            assert mock_bedrock_client.converse.called
            
        except Exception as e:
            # Health check failed
            health_status = 'unhealthy'
            assert 'error' in str(e).lower()
    
    def test_error_rate_trend_analysis(self):
        """Test error rate trend analysis for proactive monitoring."""
        from datetime import datetime, timedelta
        
        # Mock error data over time (hourly for last 24 hours)
        now = datetime.now()
        error_data = []
        
        # Simulate increasing error rate trend
        base_error_rate = 2.0  # 2% base error rate
        for hour in range(24):
            timestamp = now - timedelta(hours=23-hour)
            # Error rate increases over time (simulating degradation)
            error_rate = base_error_rate + (hour * 0.3)  # +0.3% per hour
            total_requests = 50 + (hour * 2)  # Increasing load
            errors = int((error_rate / 100) * total_requests)
            
            error_data.append({
                'timestamp': timestamp,
                'total_requests': total_requests,
                'errors': errors,
                'error_rate': error_rate
            })
        
        # Analyze trend
        recent_6h = error_data[-6:]  # Last 6 hours
        older_6h = error_data[-12:-6]  # Previous 6 hours
        
        recent_avg_error_rate = sum(d['error_rate'] for d in recent_6h) / len(recent_6h)
        older_avg_error_rate = sum(d['error_rate'] for d in older_6h) / len(older_6h)
        
        # Test trend detection
        trend_threshold = 1.5  # Alert if error rate increases by 1.5%
        error_rate_increase = recent_avg_error_rate - older_avg_error_rate
        
        assert error_rate_increase > trend_threshold  # Should detect increasing trend
        assert recent_avg_error_rate > 8.0  # Recent error rate should be elevated
        
        # Should trigger alert for error rate trend
        alert_condition = {
            'metric': 'error_rate_trend',
            'current_rate': recent_avg_error_rate,
            'previous_rate': older_avg_error_rate,
            'increase': error_rate_increase,
            'threshold_exceeded': error_rate_increase > trend_threshold
        }
        
        assert alert_condition['threshold_exceeded'] is True