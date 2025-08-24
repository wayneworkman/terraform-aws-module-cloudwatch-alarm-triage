import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from tool_handler import lambda_handler, handler, execute_python_code

class TestToolHandler:
    
    def test_handler_python_code_execution(self, mock_lambda_context):
        """Test successful Python code execution."""
        event = {
            'command': 'result = "Hello from Python"'
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Hello from Python' in body['output'] or 'Hello from Python' in body['result']
    
    def test_handler_boto3_execution(self, mock_lambda_context):
        """Test boto3 code execution."""
        event = {
            'command': '''
sts = boto3.client('sts')
result = {"account": "123456789012", "user": "test-user"}'''
        }
        
        with patch('boto3.client') as mock_client:
            mock_sts = Mock()
            mock_sts.get_caller_identity.return_value = {
                'UserId': 'AIDAI23EXAMPLE',
                'Account': '123456789012',
                'Arn': 'arn:aws:iam::123456789012:user/test-user'
            }
            mock_client.return_value = mock_sts
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
    
    def test_handler_empty_command(self, mock_lambda_context):
        """Test handling of empty command."""
        event = {
            'command': ''
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Empty command should still succeed but with minimal output
        assert body['success'] is True
    
    def test_handler_python_error(self, mock_lambda_context):
        """Test handling of Python execution errors."""
        event = {
            'command': 'raise ValueError("Test error")'
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'ValueError' in body['output']
    
    def test_handler_syntax_error(self, mock_lambda_context):
        """Test handling of Python syntax errors."""
        event = {
            'command': 'invalid python syntax here!@#$'
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'SyntaxError' in body['output'] or 'invalid syntax' in body['output']
    
    def test_handler_output_truncation(self, mock_lambda_context):
        """Test that large outputs are NOT truncated anymore."""
        event = {
            'command': 'result = "A" * 60000'  # 60KB of data
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Check that output is NOT truncated (should have full 60KB)
        assert len(body.get('result', '')) == 60000 or len(body.get('output', '')) == 60000
        # Should NOT contain truncation message
        if 'result' in body:
            assert 'truncated' not in body['result']
        if 'output' in body:
            assert 'truncated' not in body['output']
    
    def test_execute_python_code_with_result(self):
        """Test Python code execution with result variable."""
        code = '''
result = {"status": "success", "value": 42}
'''
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert '"status": "success"' in result_dict['result']
        assert result_dict['execution_time'] > 0
    
    def test_execute_python_code_with_print(self):
        """Test Python code execution with print statements."""
        code = '''
print("Starting process...")
for i in range(3):
    print(f"Step {i+1}")
print("Complete!")
result = "Done"
'''
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert 'Starting process' in result_dict['stdout']
        assert 'Step 1' in result_dict['stdout']
        assert 'Complete!' in result_dict['stdout']
        assert result_dict['result'] == 'Done'
    
    def test_execute_python_code_boto3_usage(self):
        """Test Python code using pre-imported boto3."""
        code = '''
# No import needed - boto3 is pre-imported
client = boto3.client('sts')
result = "STS client created"
'''
        with patch('boto3.client') as mock_client:
            mock_client.return_value = Mock()
            result_dict = execute_python_code(code)
            
            assert result_dict['success'] is True
            assert result_dict['result'] == 'STS client created'
    
    def test_execute_python_code_various_operations(self):
        """Test execution of various Python operations."""
        operations = [
            ('result = datetime.now().isoformat()', 'datetime'),
            ('result = json.dumps({"test": True})', 'json'),
            ('result = base64.b64encode(b"test").decode()', 'base64'),
            ('result = hashlib.sha256(b"test").hexdigest()', 'hashlib'),
            ('result = uuid.uuid4().hex', 'uuid')
        ]
        
        for code, module in operations:
            result_dict = execute_python_code(code)
            assert result_dict['success'] is True
            assert result_dict['result'] is not None
    
    def test_execute_python_code_json_operations(self):
        """Test Python code with json operations."""
        code = """
# json is pre-imported, no need to import
data = {'key': 'value', 'number': 42}
result = json.dumps(data, indent=2)
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is True
        assert 'key' in result_dict['result']
        assert 'value' in result_dict['result']
    
    def test_execute_python_code_error_handling(self):
        """Test Python code error handling."""
        code = """
raise ValueError("Test error")
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is False
        assert 'ValueError' in result_dict['stderr']
        assert 'Test error' in result_dict['stderr']
    
    def test_execute_python_code_pre_imported_modules(self):
        """Test that pre-imported modules work correctly."""
        code = """
# Test various pre-imported modules
dt = datetime.now()
td = timedelta(days=1)
pattern = re.compile(r'\\d+')
result = f"Modules work: datetime={dt.year}, timedelta={td.days}, re={bool(pattern)}"
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is True
        assert 'Modules work' in result_dict['result']
    
    def test_execute_python_code_no_import_needed(self):
        """Test that modules work without import statements."""
        code = """
# boto3 is pre-imported, no import needed
result = str(type(boto3))
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is True
        assert 'module' in result_dict['result']
    
    def test_execute_python_code_name_error(self):
        """Test Python execution name error handling."""
        code = """
# This will cause a NameError
result = undefined_variable
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is False
        assert 'NameError' in result_dict['stderr']
    
    def test_execute_python_code_json_result(self):
        """Test that dict/list results are JSON formatted."""
        code = """
result = {'name': 'test', 'values': [1, 2, 3]}
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is True
        # Should be formatted JSON
        assert '"name": "test"' in result_dict['result']
        assert '"values": [' in result_dict['result']
    
    def test_execute_python_code_no_result(self):
        """Test handling when no result variable is set."""
        code = """
x = 5
y = 10
z = x + y
print(f"Sum is {z}")
"""
        result_dict = execute_python_code(code)
        assert result_dict['success'] is True
        assert result_dict['result'] is None
        assert 'Sum is 15' in result_dict['stdout']
    
    def test_execute_python_code_boto3_client_creation(self):
        """Test boto3 client creation without imports."""
        code = """
# Create various boto3 clients
ec2 = boto3.client('ec2')
s3 = boto3.client('s3')
sts = boto3.client('sts')
result = "Clients created successfully"
"""
        with patch('boto3.client') as mock_client:
            mock_client.return_value = Mock()
            result_dict = execute_python_code(code)
            assert result_dict['success'] is True
            assert result_dict['result'] == 'Clients created successfully'
    
    def test_execute_python_code_builtins_available(self):
        """Test that standard builtins are available."""
        # Standard builtins should work
        safe_code = """
result = {
    'len_test': len([1, 2, 3]),
    'str_test': str(123),
    'type_test': str(type([]))
}
"""
        result_dict = execute_python_code(safe_code)
        assert result_dict['success'] is True
        assert '3' in result_dict['result']
        assert '123' in result_dict['result']
        assert 'list' in result_dict['result']