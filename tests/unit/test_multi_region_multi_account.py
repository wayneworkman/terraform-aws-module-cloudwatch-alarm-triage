import pytest
import json
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from bedrock_client import BedrockAgentClient
from triage_handler import handler as triage_handler, format_notification

class TestMultiRegionMultiAccount:
    """Test multi-region and multi-account production deployment scenarios."""
    
    def test_bedrock_model_region_availability_validation(self):
        """Test validation of Claude Opus 4.1 availability in different AWS regions."""
        # Claude Opus 4.1 availability by region (as of 2025)
        claude_opus_regions = {
            'us-east-1': True,      # N. Virginia - Available
            'us-west-2': True,      # Oregon - Available  
            'eu-west-1': True,      # Ireland - Available
            'ap-southeast-2': True, # Sydney - Available
            'us-west-1': False,     # N. California - Not Available
            'eu-central-1': False,  # Frankfurt - Not Available
            'ap-northeast-1': False # Tokyo - Not Available
        }
        
        def validate_bedrock_model_region(region, model_id):
            """Simulate region validation for Bedrock model availability."""
            if 'claude-opus-4-1' in model_id:
                return claude_opus_regions.get(region, False)
            return True  # Other models assumed available
        
        model_id = 'anthropic.claude-opus-4-1-20250805-v1:0'
        
        # Test supported regions
        assert validate_bedrock_model_region('us-east-1', model_id) is True
        assert validate_bedrock_model_region('us-west-2', model_id) is True
        assert validate_bedrock_model_region('eu-west-1', model_id) is True
        
        # Test unsupported regions
        assert validate_bedrock_model_region('us-west-1', model_id) is False
        assert validate_bedrock_model_region('eu-central-1', model_id) is False
        assert validate_bedrock_model_region('ap-northeast-1', model_id) is False
    
    @patch('bedrock_client.boto3.client')
    def test_bedrock_fallback_for_unsupported_regions(self, mock_boto3_client):
        """Test fallback behavior when Bedrock is unavailable in region."""
        mock_bedrock_client = Mock()
        mock_boto3_client.return_value = mock_bedrock_client
        
        # Simulate region not supported error
        mock_bedrock_client.converse.side_effect = Exception(
            "The provided model identifier is invalid or not supported in this region"
        )
        
        client = BedrockAgentClient(
            'anthropic.claude-opus-4-1-20250805-v1:0', 
            'test-arn'
        )
        
        # Should handle gracefully with fallback analysis
        result = client.investigate_with_tools("Test investigation")
        
        # Should return fallback message instead of crashing
        assert isinstance(result, dict)
        report = result['report']
        assert 'Investigation Error' in report or 'Investigation completed but no analysis was generated' in report
        assert len(report) > 100  # Should include meaningful fallback content
    
    def test_cross_account_sns_topic_arn_validation(self):
        """Test validation and handling of cross-account SNS topic ARNs."""
        # Test various SNS topic ARN formats
        test_cases = [
            {
                'arn': 'arn:aws:sns:us-east-1:123456789012:alarm-notifications',
                'valid': True,
                'cross_account': False,
                'current_account': '123456789012'
            },
            {
                'arn': 'arn:aws:sns:us-east-1:987654321098:central-alarm-topic', 
                'valid': True,
                'cross_account': True,
                'current_account': '123456789012'
            },
            {
                'arn': 'invalid-arn',
                'valid': False,
                'cross_account': False,
                'current_account': '123456789012'
            }
        ]
        
        def validate_sns_topic_arn(topic_arn, current_account_id):
            """Validate SNS topic ARN format and detect cross-account scenarios."""
            try:
                # Basic ARN format validation
                parts = topic_arn.split(':')
                if len(parts) != 6 or parts[0] != 'arn' or parts[1] != 'aws' or parts[2] != 'sns':
                    return {'valid': False, 'cross_account': False}
                
                # Extract account ID from ARN
                topic_account = parts[4]
                is_cross_account = topic_account != current_account_id
                
                return {
                    'valid': True,
                    'cross_account': is_cross_account,
                    'topic_account': topic_account,
                    'region': parts[3]
                }
            except:
                return {'valid': False, 'cross_account': False}
        
        # Test each case
        for case in test_cases:
            result = validate_sns_topic_arn(case['arn'], case['current_account'])
            assert result['valid'] == case['valid']
            if case['valid']:
                assert result['cross_account'] == case['cross_account']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:987654321098:function:cross-account-tool',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:987654321098:central-notifications',
        'DYNAMODB_TABLE': 'test-table',
        'INVESTIGATION_WINDOW_HOURS': '1'
    })
    def test_cross_account_tool_lambda_execution(self, sample_alarm_event, mock_lambda_context):
        """Test tool Lambda execution in cross-account scenarios."""
        with patch('triage_handler.BedrockAgentClient') as mock_bedrock:
            with patch('triage_handler.boto3.client') as mock_boto3:
                with patch('triage_handler.boto3.resource') as mock_boto3_resource:
                    # Mock cross-account Lambda invocation
                    mock_lambda_client = Mock()
                    mock_sns_client = Mock()
                    mock_dynamodb_table = Mock()
                    mock_dynamodb_table.get_item.return_value = {}
                    mock_dynamodb_resource = Mock()
                    mock_dynamodb_resource.Table.return_value = mock_dynamodb_table
                    mock_boto3_resource.return_value = mock_dynamodb_resource
                    
                    def client_side_effect(service_name, **kwargs):
                        if service_name == 'lambda':
                            return mock_lambda_client
                        elif service_name == 'sns':
                            return mock_sns_client
                        return Mock()
                    
                    mock_boto3.side_effect = client_side_effect
                    
                    # Mock successful cross-account Lambda invoke
                    mock_lambda_client.invoke.return_value = {
                        'StatusCode': 200,
                        'Payload': Mock(read=lambda: json.dumps({
                            'statusCode': 200,
                            'body': json.dumps({'success': True, 'output': 'Cross-account data retrieved'})
                        }).encode())
                    }
                    
                    # Mock Bedrock to use tool
                    mock_bedrock.return_value.investigate_with_tools.return_value = "Cross-account investigation complete"
                    
                    result = triage_handler(sample_alarm_event, mock_lambda_context)
                    
                    # Should succeed despite cross-account setup
                    assert result['statusCode'] == 200
                    body = json.loads(result['body'])
                    assert body['investigation_complete'] is True
                    
                    # Should publish to cross-account SNS topic
                    mock_sns_client.publish.assert_called_once()
                    call_args = mock_sns_client.publish.call_args[1]
                    assert call_args['TopicArn'] == 'arn:aws:sns:us-east-1:987654321098:central-notifications'
    
    def test_region_specific_console_url_generation(self):
        """Test console URL generation for different AWS regions."""
        # Test events from different regions
        test_events = [
            {
                'region': 'us-east-1',
                'accountId': '123456789012',
                'alarmData': {'alarmName': 'test-alarm-virginia'}
            },
            {
                'region': 'eu-west-1', 
                'accountId': '123456789012',
                'alarmData': {'alarmName': 'test-alarm-ireland'}
            },
            {
                'region': 'ap-southeast-2',
                'accountId': '123456789012', 
                'alarmData': {'alarmName': 'test-alarm-sydney'}
            }
        ]
        
        for event in test_events:
            notification = format_notification(
                event['alarmData']['alarmName'],
                'ALARM',
                'Test analysis',
                event
            )
            
            # Verify region-specific console URL
            expected_url_pattern = f"https://{event['region']}.console.aws.amazon.com/cloudwatch"
            # Console URL is constructed in format_notification - check for region presence
            assert event['region'] in notification
            assert 'console.aws.amazon.com' in notification
            
            # Verify account ID is included
            assert event['accountId'] in notification
            
            # Verify alarm name is included
            assert event['alarmData']['alarmName'] in notification
    
    def test_cross_account_iam_permissions_simulation(self):
        """Test simulation of cross-account IAM permission requirements."""
        # Simulate cross-account resource access scenarios
        cross_account_scenarios = [
            {
                'resource_type': 'cloudwatch_logs',
                'resource_arn': 'arn:aws:logs:us-east-1:987654321098:log-group:/aws/lambda/app-function',
                'required_permissions': [
                    'logs:DescribeLogGroups',
                    'logs:FilterLogEvents', 
                    'logs:GetLogEvents'
                ],
                'trust_required': True
            },
            {
                'resource_type': 'ec2_instances',
                'resource_arn': 'arn:aws:ec2:us-east-1:987654321098:instance/*',
                'required_permissions': [
                    'ec2:DescribeInstances',
                    'ec2:DescribeInstanceStatus',
                    'ec2:DescribeInstanceAttribute'
                ],
                'trust_required': True
            },
            {
                'resource_type': 'lambda_function',
                'resource_arn': 'arn:aws:lambda:us-east-1:987654321098:function:target-function',
                'required_permissions': [
                    'lambda:GetFunction',
                    'lambda:GetFunctionConfiguration',
                    'lambda:GetFunctionEventInvokeConfig'
                ],
                'trust_required': True
            }
        ]
        
        def check_cross_account_permissions(scenario, tool_role_arn):
            """Simulate cross-account permission checking."""
            tool_account = tool_role_arn.split(':')[4]
            resource_account = scenario['resource_arn'].split(':')[4]
            
            # Check if cross-account access is required
            is_cross_account = tool_account != resource_account
            
            if is_cross_account:
                # Would need assume role or resource-based policy
                return {
                    'access_granted': False,  # Would need proper setup
                    'requires_assume_role': True,
                    'required_permissions': scenario['required_permissions']
                }
            else:
                # Same account - ReadOnlyAccess policy should work
                return {
                    'access_granted': True,
                    'requires_assume_role': False,
                    'required_permissions': []
                }
        
        tool_role_arn = 'arn:aws:iam::123456789012:role/triage-tool-lambda-role'
        
        # Test each scenario
        for scenario in cross_account_scenarios:
            result = check_cross_account_permissions(scenario, tool_role_arn)
            
            # Cross-account resources should require additional setup
            assert result['requires_assume_role'] is True
            assert len(result['required_permissions']) > 0
    
    def test_multi_region_deployment_configuration_validation(self):
        """Test configuration validation for multi-region deployments."""
        # Test deployment configurations for different regions
        deployment_configs = [
            {
                'region': 'us-east-1',
                'bedrock_model_id': 'anthropic.claude-opus-4-1-20250805-v1:0',
                'tool_lambda_timeout': 300,
                'expected_valid': True
            },
            {
                'region': 'us-west-1',  # Claude Opus not available
                'bedrock_model_id': 'anthropic.claude-opus-4-1-20250805-v1:0', 
                'tool_lambda_timeout': 300,
                'expected_valid': False
            },
            {
                'region': 'eu-west-1',
                'bedrock_model_id': 'anthropic.claude-opus-4-1-20250805-v1:0',
                'tool_lambda_timeout': 1000,  # Too long (exceeds 900s max)
                'expected_valid': False
            },
            {
                'region': 'ap-southeast-2',
                'bedrock_model_id': 'anthropic.claude-haiku-3-20240307-v1:0',  # Different model
                'tool_lambda_timeout': 300,
                'expected_valid': True  # Haiku available in more regions
            }
        ]
        
        def validate_deployment_config(config):
            """Validate deployment configuration for region."""
            errors = []
            
            # Check Bedrock model availability
            if 'claude-opus-4-1' in config['bedrock_model_id']:
                supported_regions = ['us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-2']
                if config['region'] not in supported_regions:
                    errors.append(f"Claude Opus 4.1 not available in {config['region']}")
            
            # Check Lambda timeout limits (AWS Lambda max is 15 minutes = 900s)
            if config['tool_lambda_timeout'] > 900:  # 15 minutes max
                errors.append(f"Lambda timeout {config['tool_lambda_timeout']}s exceeds maximum")
            
            return {
                'valid': len(errors) == 0,
                'errors': errors
            }
        
        # Test each configuration
        for config in deployment_configs:
            result = validate_deployment_config(config)
            assert result['valid'] == config['expected_valid']
            
            if not config['expected_valid']:
                assert len(result['errors']) > 0
    
    def test_regional_data_residency_compliance(self):
        """Test data residency compliance for different regions."""
        # Test data residency requirements by region
        regional_requirements = {
            'eu-west-1': {
                'data_residency_required': True,
                'allowed_bedrock_regions': ['eu-west-1', 'eu-central-1'],
                'cross_region_data_transfer': False
            },
            'us-east-1': {
                'data_residency_required': False,
                'allowed_bedrock_regions': ['us-east-1', 'us-west-2'],
                'cross_region_data_transfer': True
            },
            'ap-southeast-2': {
                'data_residency_required': True,
                'allowed_bedrock_regions': ['ap-southeast-2'],
                'cross_region_data_transfer': False
            }
        }
        
        def check_data_residency_compliance(alarm_region, bedrock_region, requirements):
            """Check if configuration meets data residency requirements."""
            if not requirements['data_residency_required']:
                return {'compliant': True, 'warnings': []}
            
            warnings = []
            
            # Check if Bedrock region is allowed
            if bedrock_region not in requirements['allowed_bedrock_regions']:
                warnings.append(f"Bedrock region {bedrock_region} not allowed for data residency")
            
            # Check cross-region data transfer
            if alarm_region != bedrock_region and not requirements['cross_region_data_transfer']:
                warnings.append(f"Cross-region data transfer not allowed: {alarm_region} -> {bedrock_region}")
            
            return {
                'compliant': len(warnings) == 0,
                'warnings': warnings
            }
        
        # Test compliance scenarios
        test_cases = [
            ('eu-west-1', 'eu-west-1', 'eu-west-1', True),    # EU to EU - compliant
            ('eu-west-1', 'us-east-1', 'eu-west-1', False),   # EU to US - not compliant  
            ('us-east-1', 'us-west-2', 'us-east-1', True),    # US to US - compliant
            ('ap-southeast-2', 'ap-southeast-2', 'ap-southeast-2', True)  # AU to AU - compliant
        ]
        
        for alarm_region, bedrock_region, requirements_key, expected_compliant in test_cases:
            requirements = regional_requirements[requirements_key]
            result = check_data_residency_compliance(alarm_region, bedrock_region, requirements)
            assert result['compliant'] == expected_compliant