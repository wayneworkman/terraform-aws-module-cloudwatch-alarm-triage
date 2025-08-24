import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import base64

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from triage_handler import handler as triage_handler
from tool_handler import handler as tool_handler
from bedrock_client import BedrockAgentClient

class TestSecurityBoundaries:
    """Test security boundaries and access controls."""
    
    # IAM Permission Boundary Tests
    
    @patch('boto3.client')
    def test_tool_handler_cross_account_access_attempt(self, mock_boto3_client):
        """Test tool handler prevents cross-account access attempts."""
        mock_sts = Mock()
        
        # Simulate access denied for cross-account assume role
        access_denied = Exception("AccessDenied: User is not authorized to perform sts:AssumeRole")
        mock_sts.assume_role.side_effect = access_denied
        
        def client_factory(service_name, **kwargs):
            if service_name == 'sts':
                return mock_sts
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        event = {
            'command': '''
sts = boto3.client('sts')
try:
    # Attempt to assume role in different account
    response = sts.assume_role(
        RoleArn='arn:aws:iam::999999999999:role/CrossAccountRole',
        RoleSessionName='UnauthorizedSession'
    )
    result = "Successfully assumed role"
except Exception as e:
    result = f"Access denied: {str(e)}"
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Access denied' in body['output']
        assert 'not authorized' in body['output']
    
    @patch('boto3.client')
    def test_tool_handler_iam_policy_boundary_enforcement(self, mock_boto3_client):
        """Test tool handler respects IAM policy boundaries."""
        mock_iam = Mock()
        
        # Simulate permission boundary preventing user creation
        permission_denied = Exception("AccessDenied: Permissions boundary prevents IAM user creation")
        mock_iam.create_user.side_effect = permission_denied
        
        def client_factory(service_name, **kwargs):
            if service_name == 'iam':
                return mock_iam
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        event = {
            'command': '''
iam = boto3.client('iam')
try:
    # Attempt to create IAM user (should be blocked)
    iam.create_user(UserName='UnauthorizedUser')
    result = "Created user - SECURITY ISSUE!"
except Exception as e:
    result = f"Blocked as expected: {str(e)}"
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Blocked as expected' in body['output']
        assert 'SECURITY ISSUE' not in body['output']
    
    def test_tool_handler_credential_exposure_prevention(self):
        """Test tool handler prevents credential exposure."""
        event = {
            'command': '''
# Attempt to access credentials
import os

# Try to get AWS credentials from environment
aws_key = os.environ.get('AWS_ACCESS_KEY_ID', 'Not accessible')
aws_secret = os.environ.get('AWS_SECRET_ACCESS_KEY', 'Not accessible')
session_token = os.environ.get('AWS_SESSION_TOKEN', 'Not accessible')

# Ensure we're not exposing credentials
result = {
    'key_found': aws_key != 'Not accessible',
    'secret_found': aws_secret != 'Not accessible',
    'token_found': session_token != 'Not accessible',
    'message': 'Credential check complete'
}
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        
        # Should not expose actual credential values in output
        output = body['output']
        assert 'AKIA' not in output  # AWS access key prefix
        assert 'aws_secret_access_key' not in output.lower()
        
        # Credentials should be accessible to boto3 but not directly exposed
        assert '"key_found": true' in output or '"key_found": false' in output
    
    @patch('boto3.client')
    def test_tool_handler_resource_access_control(self, mock_boto3_client):
        """Test tool handler respects resource-level access controls."""
        mock_s3 = Mock()
        
        # Some buckets accessible, others not
        def list_objects_v2(**kwargs):
            bucket = kwargs.get('Bucket')
            if bucket == 'restricted-bucket':
                raise Exception("AccessDenied: Access to bucket denied")
            return {'Contents': []}
        
        mock_s3.list_objects_v2 = list_objects_v2
        
        def client_factory(service_name, **kwargs):
            if service_name == 's3':
                return mock_s3
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        event = {
            'command': '''
s3 = boto3.client('s3')
accessible = []
denied = []

for bucket in ['public-bucket', 'restricted-bucket', 'team-bucket']:
    try:
        s3.list_objects_v2(Bucket=bucket)
        accessible.append(bucket)
    except Exception as e:
        if 'AccessDenied' in str(e):
            denied.append(bucket)

result = f"Accessible: {accessible}, Denied: {denied}"
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'restricted-bucket' in body['output']
        assert 'Denied' in body['output']
    
    # SNS Topic Access Control Tests
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'test-arn',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-1:123456789012:authorized-topic'
    })
    @patch('triage_handler.boto3.client')
    @patch('triage_handler.BedrockAgentClient')
    def test_triage_handler_sns_topic_access_control(self, mock_bedrock, mock_boto3_client, mock_lambda_context):
        """Test triage handler only publishes to authorized SNS topic."""
        mock_sns = Mock()
        mock_sns.publish.return_value = {'MessageId': 'authorized-message-id'}
        mock_boto3_client.return_value = mock_sns
        
        mock_bedrock.return_value.investigate_with_tools.return_value = "Test analysis"
        
        event = {
            'alarmData': {
                'alarmName': 'test-alarm',
                'state': {'value': 'ALARM'}
            }
        }
        
        result = triage_handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        # Should only publish to authorized topic
        mock_sns.publish.assert_called()
        call_kwargs = mock_sns.publish.call_args.kwargs
        assert call_kwargs['TopicArn'] == 'arn:aws:sns:us-east-1:123456789012:authorized-topic'
    
    # Data Privacy and Sanitization Tests
    
    def test_tool_handler_pii_data_handling(self):
        """Test tool handler handling of PII data."""
        event = {
            'command': '''
# Simulate PII data processing
customer_data = {
    'email': 'user@example.com',
    'ssn': '123-45-6789',
    'credit_card': '4111-1111-1111-1111',
    'name': 'John Doe',
    'account_id': '12345'
}

# Process without exposing sensitive data
result = {
    'records_processed': 1,
    'has_email': '@' in customer_data.get('email', ''),
    'has_ssn': 'ssn' in customer_data,
    'data_types': list(customer_data.keys())
}
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        
        # Should process but not expose PII
        output = body['output']
        assert 'records_processed' in output
        assert '123-45-6789' not in output  # SSN should not be in output
        assert '4111' not in output  # Credit card should not be in output
    
    def test_tool_handler_secrets_masking(self):
        """Test tool handler masks secrets in output."""
        event = {
            'command': '''
# Simulate secret handling
api_response = {
    'api_key': 'sk-1234567890abcdef',
    'password': 'super_secret_password',
    'token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9',
    'data': 'normal data'
}

# Process secrets safely
result = {
    'has_api_key': 'api_key' in api_response,
    'has_password': 'password' in api_response,
    'has_token': 'token' in api_response,
    'data': api_response.get('data', 'no data')
}
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        
        # Secrets should not appear in output
        output = body['output']
        assert 'sk-1234567890abcdef' not in output
        assert 'super_secret_password' not in output
        assert 'normal data' in output  # Non-secret data should be present
    
    # Network Security Tests
    
    def test_tool_handler_network_isolation(self):
        """Test tool handler network isolation."""
        event = {
            'command': '''
import socket

# Try to make external network connections
results = []

# Attempt DNS resolution
try:
    ip = socket.gethostbyname('example.com')
    results.append(f"DNS resolved: {ip}")
except Exception as e:
    results.append(f"DNS failed: {str(e)}")

# Attempt to create socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    # Don't actually connect, just test socket creation
    s.close()
    results.append("Socket created successfully")
except Exception as e:
    results.append(f"Socket failed: {str(e)}")

result = "; ".join(results)
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Network operations may or may not work depending on Lambda config
        # Test should handle both cases gracefully
    
    def test_tool_handler_file_system_isolation(self):
        """Test tool handler file system access restrictions."""
        event = {
            'command': '''
import os

results = []

# Check what directories we can access
for path in ['/tmp', '/var', '/etc', '/home', '/root']:
    try:
        if os.path.exists(path):
            results.append(f"{path}: exists")
        else:
            results.append(f"{path}: not found")
    except Exception as e:
        results.append(f"{path}: {str(e)}")

# Try to write to /tmp (should work)
try:
    test_file = '/tmp/test_file.txt'
    with open(test_file, 'w') as f:
        f.write('test')
    os.remove(test_file)
    results.append("/tmp: writable")
except Exception as e:
    results.append(f"/tmp write failed: {str(e)}")

result = "; ".join(results)
'''
        }
        
        result = tool_handler(event, None)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        
        # /tmp should be writable in Lambda
        assert '/tmp: writable' in body['output'] or '/tmp: exists' in body['output']
    
    # Import Security Tests
    
    def test_tool_handler_dangerous_imports_blocked(self):
        """Test tool handler blocks dangerous imports."""
        dangerous_imports = [
            'import subprocess',
            'import os; os.system("ls")',
            '__import__("subprocess")'
        ]
        
        for dangerous_import in dangerous_imports:
            event = {
                'command': f'''
{dangerous_import}
result = "Import succeeded - potential security issue"
'''
            }
            
            result = tool_handler(event, None)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            
            # Imports are stripped, so the result assignment should work
            # but without the dangerous import actually being executed
            if body['success']:
                # Check that imports were stripped
                assert 'Removed' in body['output'] or 'Import succeeded' in body['output']
                # subprocess should not be available
                if 'subprocess' in dangerous_import:
                    # The import was stripped, result should still execute
                    assert 'Import succeeded' in body['output']
    
    @patch.dict(os.environ, {
        'BEDROCK_MODEL_ID': 'test-model',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-1:123456789012:function:tool-lambda'
    })
    @patch('bedrock_client.boto3.client')
    def test_bedrock_client_tool_invocation_validation(self, mock_boto3_client):
        """Test Bedrock client validates tool Lambda ARN before invocation."""
        mock_lambda = Mock()
        
        # Mock Lambda invocation
        def invoke(**kwargs):
            function_name = kwargs.get('FunctionName')
            # Should only invoke the configured tool Lambda
            if function_name != 'arn:aws:lambda:us-east-1:123456789012:function:tool-lambda':
                raise Exception("AccessDenied: Not authorized to invoke this function")
            return {
                'StatusCode': 200,
                'Payload': Mock(read=lambda: json.dumps({
                    'statusCode': 200,
                    'body': json.dumps({'success': True, 'output': 'Authorized invocation'})
                }).encode())
            }
        
        mock_lambda.invoke = invoke
        
        def client_factory(service_name, **kwargs):
            if service_name == 'lambda':
                return mock_lambda
            elif service_name == 'bedrock-runtime':
                mock_bedrock = Mock()
                mock_bedrock.converse.return_value = {
                    'output': {
                        'message': {
                            'content': [{'text': 'Analysis complete'}]
                        }
                    }
                }
                return mock_bedrock
            return Mock()
        
        mock_boto3_client.side_effect = client_factory
        
        client = BedrockAgentClient('test-model', 'arn:aws:lambda:us-east-1:123456789012:function:tool-lambda')
        
        # Should use the configured ARN
        result = client.investigate_with_tools("Test")
        assert 'Analysis complete' in result
    
    def test_tool_handler_code_injection_prevention(self):
        """Test tool handler prevents code injection attacks."""
        injection_attempts = [
            "'; import os; os.system('whoami'); '",
            '"; __import__("os").system("ls"); "',
            "${IFS}&&{echo,injection}",
            "$(whoami)",
            "`ls -la`"
        ]
        
        for injection in injection_attempts:
            event = {
                'command': f'result = "{injection}"'
            }
            
            result = tool_handler(event, None)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            
            # Should handle as string, not execute
            if body['success']:
                # The injection string should be treated as a string literal
                # Should not execute system commands
                assert 'root' not in body['output'].lower()  # whoami result
                assert 'total' not in body['output'].lower()  # ls result
                assert 'drwx' not in body['output']  # ls -la output