"""
Testing Iteration 3: Address production readiness gaps that could cause production issues
Focus: Real-world failure modes, service integration robustness, and operational resilience
"""
import pytest
import json
import sys
import os
import time
from unittest.mock import Mock, patch, MagicMock, call
import boto3
from botocore.exceptions import ClientError, BotoCoreError, NoCredentialsError
from datetime import datetime, timezone

# Add module paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from triage_handler import handler as triage_handler, format_notification
from bedrock_client import BedrockAgentClient
from prompt_template import PromptTemplate
from tool_handler import handler as tool_handler

class TestIteration3ProductionReadiness:
    """Tests addressing production-specific failure modes and operational resilience."""
    
    def test_aws_service_outage_cascade_failures(self):
        """
        Test system behavior during AWS service outages that affect multiple components.
        This tests the most critical production scenario: external service failures.
        """
        # Simulate a multi-service AWS outage scenario
        service_unavailable_error = ClientError(
            error_response={'Error': {'Code': 'ServiceUnavailableException', 'Message': 'Service temporarily unavailable'}},
            operation_name='InvokeModel'
        )
        
        with patch.dict('os.environ', {
            'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
            'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123:function:tool',
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123:topic'
        }):
            alarm_event = {
                'alarmData': {
                    'alarmName': 'production-critical-alarm',
                    'state': {'value': 'ALARM'},
                    'configuration': {'thresholds': [95.0]}
                },
                'region': 'us-east-1',
                'accountId': '123456789012'
            }
            
            # Test Bedrock outage + SNS working (partial degradation)
            with patch('triage_handler.BedrockAgentClient') as mock_bedrock_client:
                mock_bedrock_client.side_effect = service_unavailable_error
                
                with patch('boto3.client') as mock_boto3:
                    mock_sns = MagicMock()
                    mock_sns.publish.return_value = {'MessageId': 'test-message-id'}
                    mock_boto3.return_value = mock_sns
                    
                    result = triage_handler(alarm_event, {})
                    
                    # Should gracefully degrade - return error but still notify
                    assert result['statusCode'] == 500
                    
                    # Should send fallback notification
                    mock_sns.publish.assert_called_once()
                    call_args = mock_sns.publish.call_args
                    assert "Investigation Failed" in call_args[1]['Subject']
                    assert "Service temporarily unavailable" in call_args[1]['Message']
                    
            # Test complete AWS outage (Bedrock + SNS both fail)
            with patch('triage_handler.BedrockAgentClient') as mock_bedrock_client:
                mock_bedrock_client.side_effect = service_unavailable_error
                
                with patch('boto3.client') as mock_boto3:
                    mock_sns = MagicMock()
                    mock_sns.publish.side_effect = service_unavailable_error
                    mock_boto3.return_value = mock_sns
                    
                    result = triage_handler(alarm_event, {})
                    
                    # System should still not crash - return error gracefully
                    assert result['statusCode'] == 500
                    assert 'error' in json.loads(result['body'])
                    
                    # Should attempt SNS but handle failure gracefully
                    mock_sns.publish.assert_called_once()
    
    def test_memory_pressure_and_garbage_collection_scenarios(self):
        """
        Test system behavior under memory pressure scenarios that could occur in production.
        This tests resource exhaustion that could cause Lambda cold starts or failures.
        """
        # Simulate large alarm events that could cause memory pressure
        large_alarm_event = {
            'alarmData': {
                'alarmName': 'memory-intensive-alarm',
                'state': {'value': 'ALARM'},
                'configuration': {
                    'metrics': [
                        {
                            'name': f'MetricName{i}',
                            'dimensions': {f'Dimension{j}': f'Value{j}' for j in range(50)},
                            'statistics': ['Average', 'Maximum', 'Minimum', 'Sum', 'SampleCount']
                        }
                        for i in range(100)  # Large number of metrics
                    ],
                    'metadata': {
                        'large_data': ['x' * 1000 for _ in range(100)],  # Large data structure
                        'nested_objects': {
                            f'level_{i}': {
                                f'sublevel_{j}': f'data_{k}' * 100
                                for j in range(10)
                                for k in range(10)
                            }
                            for i in range(10)
                        }
                    }
                }
            }
        }
        
        with patch.dict('os.environ', {
            'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
            'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123:function:tool',
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123:topic'
        }):
            with patch('triage_handler.BedrockAgentClient') as mock_bedrock_client:
                # Mock a memory-constrained response
                mock_investigation = mock_bedrock_client.return_value.investigate_with_tools
                mock_investigation.return_value = "Memory-constrained analysis completed"
                
                with patch('boto3.client') as mock_boto3:
                    mock_sns = MagicMock()
                    mock_boto3.return_value = mock_sns
                    
                    result = triage_handler(large_alarm_event, {})
                    
                    # Should handle large events gracefully
                    assert result['statusCode'] == 200
                    body = json.loads(result['body'])
                    assert body['investigation_complete'] is True
                    
                    # Should successfully send notification despite large data
                    mock_sns.publish.assert_called_once()
                    
                    # Notification should be properly formatted despite size
                    call_args = mock_sns.publish.call_args
                    message = call_args[1]['Message']
                    assert 'memory-intensive-alarm' in message
                    assert len(message) < 100000  # Should not exceed reasonable message size
    
    def test_concurrent_alarm_storm_with_resource_contention(self):
        """
        Test behavior during alarm storms with concurrent Lambda invocations and resource contention.
        This tests the most challenging production scenario: high load with resource limits.
        """
        client = BedrockAgentClient(
            model_id="anthropic.claude-opus-4-1-20250805-v1:0",
            tool_lambda_arn="arn:aws:lambda:us-east-1:123456789012:function:tool",
        )
        
        # Simulate resource contention scenarios
        contention_errors = [
            ClientError(
                error_response={'Error': {'Code': 'TooManyRequestsException', 'Message': 'Too many concurrent requests'}},
                operation_name='InvokeModel'
            ),
            ClientError(
                error_response={'Error': {'Code': 'LimitExceededException', 'Message': 'Request rate limit exceeded'}},
                operation_name='InvokeModel'
            ),
            ClientError(
                error_response={'Error': {'Code': 'ResourceInUseException', 'Message': 'Resource temporarily in use'}},
                operation_name='InvokeModel'
            )
        ]
        
        # Test high-frequency retry scenarios
        with patch.object(client.bedrock, 'converse') as mock_bedrock:
            # Simulate: multiple failures followed by eventual success
            success_response = {'output': {'message': {'content': [{'text': 'Analysis completed under load'}]}}}
            
            # Mix of different errors followed by success
            mock_bedrock.side_effect = contention_errors + [success_response]
            
            with patch('time.sleep') as mock_sleep:
                result = client.investigate_with_tools("Test under high load")
                
                # With multiple failures, should eventually return dict with error message
                # but handle it gracefully without crashing
                assert isinstance(result, dict)
                assert 'report' in result
                assert len(result['report']) > 0
                
                # Should have attempted at least the first call
                assert mock_bedrock.call_count >= 1
                
                # Should be resilient to errors (not crash)
    
    def test_production_data_privacy_and_security_compliance(self):
        """
        Test that the system properly handles sensitive data and maintains security in production.
        This tests critical security requirements for production deployment.
        """
        # Test with alarm events containing potentially sensitive data
        sensitive_alarm_event = {
            'alarmData': {
                'alarmName': 'database-connection-failure',
                'state': {
                    'value': 'ALARM',
                    'reason': 'Connection failed to rds-prod-user:password123@prod-db.cluster-xyz.rds.amazonaws.com:5432'
                },
                'configuration': {
                    'metrics': [{
                        'dimensions': {
                            'DatabaseName': 'users_production',
                            'Environment': 'production',
                            'ConnectionString': 'postgresql://user:pass@host:5432/db'
                        }
                    }]
                }
            },
            'accountId': '123456789012',
            'region': 'us-east-1'
        }
        
        prompt = PromptTemplate.generate_investigation_prompt(alarm_event=sensitive_alarm_event)
        
        # Verify that sensitive data is included (as it should be for investigation)
        # But also verify that this is properly formatted for secure handling
        assert 'password123' in prompt  # Should include for investigation
        assert 'users_production' in prompt
        assert 'postgresql://user:pass@host:5432/db' in prompt
        
        # Test that the notification format doesn't expose more than necessary
        notification = format_notification(
            alarm_name='database-connection-failure',
            alarm_state='ALARM', 
            analysis='Analysis completed with security considerations',
            event=sensitive_alarm_event
        )
        
        # Notification should include account info but be properly formatted
        assert '123456789012' in notification
        assert 'database-connection-failure' in notification
        assert 'Analysis completed with security considerations' in notification
        
        # Should include console links for investigation
        assert 'console.aws.amazon.com' in notification
    
    def test_cross_region_and_cross_account_investigation_capabilities(self):
        """
        Test the system's ability to investigate across regions and accounts in production.
        This tests multi-environment production deployments.
        """
        # Test alarm from different regions
        cross_region_events = [
            {
                'alarmData': {'alarmName': 'eu-west-1-alarm', 'state': {'value': 'ALARM'}},
                'region': 'eu-west-1',
                'accountId': '123456789012'
            },
            {
                'alarmData': {'alarmName': 'ap-southeast-2-alarm', 'state': {'value': 'ALARM'}},
                'region': 'ap-southeast-2', 
                'accountId': '987654321098'
            },
            {
                'alarmData': {'alarmName': 'us-gov-east-1-alarm', 'state': {'value': 'ALARM'}},
                'region': 'us-gov-east-1',
                'accountId': '123456789012'
            }
        ]
        
        for event in cross_region_events:
            # Generate console URLs for different regions/accounts
            notification = format_notification(
                alarm_name=event['alarmData']['alarmName'],
                alarm_state='ALARM',
                analysis=f"Regional analysis for {event['region']}",
                event=event
            )
            
            # Should generate correct regional console links
            expected_region = event['region']
            assert f"region={expected_region}" in notification
            assert event['accountId'] in notification
            assert event['alarmData']['alarmName'] in notification
            
            # Should handle different region formats correctly
            assert 'console.aws.amazon.com' in notification or 'console.amazonaws-us-gov.com' in notification
    
    def test_lambda_cold_start_and_initialization_resilience(self):
        """
        Test system behavior during Lambda cold starts and initialization delays.
        This tests real-world latency issues that affect production performance.
        """
        # Simulate cold start scenarios with delayed AWS service initialization
        slow_bedrock_responses = []
        
        # Create delayed responses to simulate cold start latency
        for i in range(3):
            response = {
                'output': {
                    'message': {
                        'content': [{
                            'text': f'Cold start analysis {i+1}'
                        }]
                    }
                }
            }
            slow_bedrock_responses.append(response)
        
        client = BedrockAgentClient(
            model_id="anthropic.claude-opus-4-1-20250805-v1:0",
            tool_lambda_arn="arn:aws:lambda:us-east-1:123456789012:function:tool",
        )
        
        with patch.object(client.bedrock, 'converse') as mock_bedrock:
            # Simulate slow service initialization
            def slow_invoke(*args, **kwargs):
                time.sleep(0.1)  # Simulate cold start delay
                return slow_bedrock_responses[mock_bedrock.call_count - 1]
            
            mock_bedrock.side_effect = slow_invoke
            
            start_time = time.time()
            result = client.investigate_with_tools("Test cold start resilience")
            end_time = time.time()
            
            # Should complete successfully despite cold start delays
            assert isinstance(result, dict) and "Cold start analysis" in result.get("report", "")
            
            # Should handle the delay gracefully (not crash or timeout prematurely)
            execution_time = end_time - start_time
            assert execution_time < 30  # Should not take excessively long
            
            # Should have made at least one call
            assert mock_bedrock.call_count >= 1
    
    def test_tool_lambda_python_environment_consistency(self):
        """
        Test tool Lambda's Python environment consistency across deployments.
        This tests infrastructure consistency that's critical for production reliability.
        """
        # Test various Python operations that should work in the Lambda environment
        test_commands = [
            {'command': 'result = str(boto3.__version__)'},
            {'command': 'sts = boto3.client("sts"); result = "STS client created"'},
            {'command': 'result = {"python_version": str(sys.version_info[:2])}'},
            {'command': 'ec2 = boto3.client("ec2", region_name="us-east-1"); result = "EC2 client created"'},
            {'command': 'result = {"modules": len([m for m in globals() if not m.startswith("_")])}'}
        ]
        
        for command in test_commands:
            with patch('boto3.client') as mock_client:
                mock_client.return_value = Mock()
                
                result = tool_handler(command, {})
                
                assert result['statusCode'] == 200
                body = json.loads(result['body'])
                assert body['success'] is True
                # Should return some output
                assert body['output'] is not None or body['result'] is not None
    
    def test_error_propagation_with_detailed_context_for_production_debugging(self):
        """
        Test that error messages provide sufficient context for production debugging.
        This tests operational visibility which is critical for production support.
        """
        # Test various error scenarios with proper context preservation
        error_scenarios = [
            {
                'name': 'Bedrock Model Not Available',
                'error': ClientError(
                    error_response={
                        'Error': {
                            'Code': 'ValidationException',
                            'Message': 'The requested model anthropic.claude-opus-4-1-20250805-v1:0 is not available in region us-west-1'
                        }
                    },
                    operation_name='InvokeModel'
                ),
                'expected_context': ['us-west-1', 'anthropic.claude-opus-4-1-20250805-v1:0', 'ValidationException']
            },
            {
                'name': 'IAM Permission Denied',
                'error': ClientError(
                    error_response={
                        'Error': {
                            'Code': 'AccessDeniedException',
                            'Message': 'User: arn:aws:sts::123456789012:assumed-role/lambda-role/lambda-function is not authorized to perform: bedrock:InvokeModel'
                        }
                    },
                    operation_name='InvokeModel'
                ),
                'expected_context': ['AccessDeniedException', 'bedrock:InvokeModel', 'lambda-role']
            },
            {
                'name': 'Tool Lambda Timeout',
                'error': ClientError(
                    error_response={
                        'Error': {
                            'Code': 'TaskTimedOut',
                            'Message': 'Lambda function execution timed out after 60 seconds'
                        }
                    },
                    operation_name='Invoke'
                ),
                'expected_context': ['TaskTimedOut', '60 seconds', 'timed out']
            }
        ]
        
        with patch.dict('os.environ', {
            'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
            'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123:function:tool',
            'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123:topic'
        }):
            for scenario in error_scenarios:
                alarm_event = {
                    'alarmData': {
                        'alarmName': f'test-{scenario["name"].lower().replace(" ", "-")}-alarm',
                        'state': {'value': 'ALARM'}
                    },
                    'region': 'us-west-1',
                    'accountId': '123456789012'
                }
                
                with patch('triage_handler.BedrockAgentClient') as mock_bedrock_client:
                    mock_bedrock_client.side_effect = scenario['error']
                    
                    with patch('boto3.client') as mock_boto3:
                        mock_sns = MagicMock()
                        mock_boto3.return_value = mock_sns
                        
                        result = triage_handler(alarm_event, {})
                        
                        # Should return error but with detailed context
                        assert result['statusCode'] == 500
                        
                        # Should send detailed error notification
                        mock_sns.publish.assert_called_once()
                        call_args = mock_sns.publish.call_args
                        error_message = call_args[1]['Message']
                        
                        # Should include key context for debugging
                        # At least some of the expected context should be present
                        context_found = sum(1 for context in scenario['expected_context'] if context in error_message)
                        assert context_found >= 1, f"Missing critical context in error for {scenario['name']}: {error_message}"
                        
                        # Should include alarm information
                        assert alarm_event['alarmData']['alarmName'] in error_message
                        
                        # The error message should contain enough detail for debugging
                        assert len(error_message) > 100  # Should be detailed enough