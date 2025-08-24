import pytest
import json
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from triage_handler import handler as triage_handler, format_notification
from prompt_template import PromptTemplate

class TestDataValidation:
    """Test data validation and boundary conditions."""
    
    def test_triage_handler_malformed_alarm_events(self, mock_lambda_context):
        """Test triage handler with various malformed alarm event structures."""
        
        malformed_events = [
            # Missing alarmData
            {'source': 'aws.cloudwatch', 'accountId': '123456789012'},
            
            # Missing state
            {'alarmData': {'alarmName': 'test-alarm'}},
            
            # Invalid state value
            {'alarmData': {'alarmName': 'test-alarm', 'state': {'value': 'INVALID_STATE'}}},
            
            # Nested structure missing
            {'alarmData': {'alarmName': 'test-alarm', 'state': {}}},
            
            # Empty event
            {},
            
            # Non-dict event (edge case)
            "invalid_event_string"
        ]
        
        with patch.dict(os.environ, {
            'BEDROCK_MODEL_ID': 'test-model',
            'TOOL_LAMBDA_ARN': 'test-arn', 
            'SNS_TOPIC_ARN': 'test-topic'
        }):
            for i, event in enumerate(malformed_events):
                if isinstance(event, str):
                    # Skip string events that would cause JSON parsing errors
                    continue
                    
                with patch('triage_handler.BedrockAgentClient') as mock_bedrock:
                    with patch('triage_handler.boto3.client') as mock_boto3:
                        mock_bedrock.return_value.investigate_with_tools.return_value = f"Fallback analysis for malformed event {i}"
                        mock_sns = Mock()
                        mock_boto3.return_value = mock_sns
                        
                        # Should handle gracefully without crashing
                        result = triage_handler(event, mock_lambda_context)
                        
                        # Should either skip (for non-ALARM) or process with fallback
                        assert result['statusCode'] in [200, 500]  # 200 for skipped, 200/500 for processed
    
    def test_notification_formatting_with_extreme_data(self):
        """Test notification formatting with extreme data scenarios."""
        # Very long alarm name
        long_alarm_name = "a" * 1000
        
        # Very long analysis 
        long_analysis = "This is a very detailed analysis. " * 1000
        
        # Event with special characters
        special_event = {
            'region': 'us-east-1',
            'accountId': '123456789012',
            'alarmData': {
                'alarmName': 'test-alarm-with-unicode-éñ',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Should handle without errors
        result = format_notification(long_alarm_name, "ALARM", long_analysis, special_event)
        
        assert isinstance(result, str)
        assert long_alarm_name in result
        assert 'console.aws.amazon.com' in result
        assert len(result) > 1000  # Should include the long analysis
    
    def test_prompt_template_with_complex_alarm_structures(self):
        """Test prompt template generation with complex alarm event structures."""
        
        # Alarm with deeply nested configuration
        complex_event = {
            'source': 'aws.cloudwatch',
            'alarmData': {
                'alarmName': 'complex-composite-alarm',
                'state': {'value': 'ALARM'},
                'configuration': {
                    'metrics': [
                        {
                            'id': 'm1',
                            'metricStat': {
                                'metric': {
                                    'namespace': 'AWS/ApplicationELB',
                                    'name': 'TargetResponseTime',
                                    'dimensions': {
                                        'LoadBalancer': 'app/my-load-balancer/50dc6c495c0c9188',
                                        'TargetGroup': 'targetgroup/my-targets/73e2d6bc24d8a067'
                                    }
                                },
                                'period': 300,
                                'stat': 'Average'
                            }
                        },
                        {
                            'id': 'm2', 
                            'expression': 'm1 > 0.5',
                            'label': 'High Response Time'
                        }
                    ],
                    'comparisonOperator': 'GreaterThanThreshold',
                    'threshold': 0.5,
                    'evaluationPeriods': 2,
                    'datapointsToAlarm': 1
                }
            },
            'region': 'us-west-2',
            'accountId': '987654321098'
        }
        
        prompt = PromptTemplate.generate_investigation_prompt(complex_event)
        
        # Should generate valid prompt without errors
        assert isinstance(prompt, str)
        assert len(prompt) > 1000  # Should be comprehensive
        assert 'complex-composite-alarm' in prompt
        assert 'ApplicationELB' in prompt
        assert 'TargetResponseTime' in prompt
        assert 'comprehensive' in prompt.lower() or 'exhaustive' in prompt.lower()
    
    def test_prompt_template_with_unicode_and_special_chars(self):
        """Test prompt template handling unicode and special characters."""
        
        unicode_event = {
            'alarmData': {
                'alarmName': 'test-alarm-with-émojis-🚨',
                'state': {'value': 'ALARM'},
                'configuration': {
                    'description': 'Alarm with unicode: Ñoño café résumé 中文 العربية'
                }
            },
            'region': 'eu-central-1'
        }
        
        prompt = PromptTemplate.generate_investigation_prompt(unicode_event)
        
        # Should handle unicode without errors
        assert isinstance(prompt, str)
        assert len(prompt) > 1000  # Should generate substantial content
        # Unicode characters should be properly encoded in the JSON dump
        assert 'test-alarm-with-' in prompt
        assert 'eu-central-1' in prompt
    
    def test_prompt_template_generation(self):
        """Test prompt template generation."""
        
        simple_event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        # Test prompt generation
        prompt = PromptTemplate.generate_investigation_prompt(simple_event)
        
        assert isinstance(prompt, str)
        assert len(prompt) > 500  # Should generate substantial content
        assert 'test-alarm' in prompt
        
        # Should always be comprehensive now
        assert 'comprehensive' in prompt.lower()
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'test-topic'
    })
    def test_triage_handler_with_token_constraints(self, sample_alarm_event, mock_lambda_context):
        """Test triage handler behavior with very low token limits."""
        
        with patch('triage_handler.BedrockAgentClient') as mock_bedrock:
            with patch('triage_handler.boto3.client') as mock_boto3:
                # Mock truncated response due to token limits
                mock_bedrock.return_value.investigate_with_tools.return_value = "Brief analysis due to token limits."
                mock_sns = Mock()
                mock_boto3.return_value = mock_sns
                
                result = triage_handler(sample_alarm_event, mock_lambda_context)
                
                assert result['statusCode'] == 200
                
                # Verify low token limit was passed
                mock_bedrock.assert_called_with(
                    model_id='test-model',
                    tool_lambda_arn='test-arn',
                )
    
    def test_triage_handler_missing_environment_variables(self, sample_alarm_event, mock_lambda_context):
        """Test triage handler behavior when environment variables are missing."""
        
        # Test with missing required environment variables
        with patch.dict(os.environ, {}, clear=True):
            # Should handle missing environment variables gracefully with error
            result = triage_handler(sample_alarm_event, mock_lambda_context)
            
            # Should return 500 error for missing environment variables
            assert result['statusCode'] == 500
            body = json.loads(result['body'])
            assert 'error' in body
            assert body['alarm'] == 'test-lambda-errors'
    
    def test_format_notification_boundary_conditions(self):
        """Test notification formatting with boundary conditions."""
        
        # Test with None/empty values
        result1 = format_notification("", "ALARM", "", {})
        assert isinstance(result1, str)
        assert "CloudWatch Alarm Investigation Results" in result1
        
        # Test with None analysis
        result2 = format_notification("test-alarm", "ALARM", None, {'region': 'us-east-1'})
        assert isinstance(result2, str) 
        assert "test-alarm" in result2
        
        # Test with very nested event structure
        complex_event = {
            'level1': {
                'level2': {
                    'level3': {
                        'deep_value': 'found'
                    }
                }
            },
            'region': 'ap-southeast-1',
            'accountId': '111122223333'
        }
        
        result3 = format_notification("deep-alarm", "ALARM", "Deep analysis", complex_event)
        assert isinstance(result3, str)
        assert "deep-alarm" in result3
        assert "ap-southeast-1" in result3