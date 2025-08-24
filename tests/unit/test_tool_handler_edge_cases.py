import pytest
import json
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from tool_handler import handler, lambda_handler, execute_python_code

class TestToolHandlerEdgeCases:
    """Test edge cases and error scenarios for tool handler."""
    
    def test_python_code_no_output(self, mock_lambda_context):
        """Test Python code that completes successfully but produces no output."""
        event = {
            'command': 'x = 5; y = 10'  # No result or print
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert body['result'] is None
        assert body['stdout'] == ''
    
    def test_python_code_with_print_and_result(self, mock_lambda_context):
        """Test Python code that has both print output and result."""
        event = {
            'command': '''
print("Processing...")
result = {"status": "complete", "value": 42}
print("Done!")
'''
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Processing...' in body['stdout']
        assert 'Done!' in body['stdout']
        assert '"status": "complete"' in body['result']
    
    def test_python_code_stdout_restoration_on_exception(self, mock_lambda_context):
        """Test that stdout is restored even when Python execution throws exception."""
        event = {
            'command': 'raise ValueError("Test exception")'
        }
        
        # Verify stdout is restored after exception
        import sys
        original_stdout = sys.stdout
        
        result = handler(event, mock_lambda_context)
        
        # Check stdout was restored
        assert sys.stdout is original_stdout
        
        assert result['statusCode'] == 200  # Error status
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'ValueError' in body['output']
        assert 'Test exception' in body['output']
    
    def test_python_code_syntax_error(self, mock_lambda_context):
        """Test handling of Python syntax errors."""
        event = {
            'command': 'def broken syntax here'
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'SyntaxError' in body['output'] or 'invalid syntax' in body['output']
    
    def test_python_code_undefined_variable(self, mock_lambda_context):
        """Test handling of undefined variable access."""
        event = {
            'command': 'result = undefined_var * 2'
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'NameError' in body['output']
    
    def test_execute_python_code_complex_namespace_operations(self, mock_lambda_context):
        """Test complex namespace operations in Python execution."""
        code = '''
# Test namespace isolation
local_var = 100
globals_before = len(globals())
locals_before = len(locals())

# Test that builtins work
result = {
    'sum': sum([1, 2, 3]),
    'max': max([5, 2, 8]),
    'sorted': sorted([3, 1, 2])
}
'''
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert '"sum": 6' in result_dict['result']
        assert '"max": 8' in result_dict['result']
        # JSON formatting might vary, check values are present
        assert '"sum": 6' in result_dict['result']
        assert '"max": 8' in result_dict['result']
        assert '1' in result_dict['result'] and '2' in result_dict['result'] and '3' in result_dict['result']
    
    def test_python_code_module_usage_without_import(self, mock_lambda_context):
        """Test that pre-imported modules work without import statements."""
        event = {
            'command': '''
# Use pre-imported modules directly
dt = datetime.now()
b64 = base64.b64encode(b"test").decode()
uid = uuid.uuid4().hex[:8]
result = f"datetime={dt.year}, base64={b64}, uuid_len={len(uid)}"
'''
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'datetime=' in body['result']
        assert 'base64=dGVzdA==' in body['result']
        assert 'uuid_len=8' in body['result']
    
    def test_python_code_boto3_client_error_handling(self, mock_lambda_context):
        """Test handling of boto3 client errors."""
        event = {
            'command': '''
try:
    s3 = boto3.client('s3')
    # This would fail with access denied in real execution
    s3.get_object(Bucket='restricted-bucket', Key='secret.txt')
    result = "Should not reach here"
except Exception as e:
    result = f"Expected error: {type(e).__name__}"
'''
        }
        
        with patch('boto3.client') as mock_client:
            mock_s3 = Mock()
            mock_s3.get_object.side_effect = Exception("AccessDenied")
            mock_client.return_value = mock_s3
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
            assert 'Expected error' in body['result']
    
    def test_large_output_truncation(self, mock_lambda_context):
        """Test that large outputs are NOT truncated anymore."""
        event = {
            'command': 'result = "X" * 60000'  # 60KB of data
        }
        
        # MAX_OUTPUT_SIZE env var is no longer used
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        # Check that result is NOT truncated (full 60KB)
        assert len(body['result']) == 60000
        # Should NOT contain truncation message
        assert 'truncated' not in body['result']
    
    def test_empty_command(self, mock_lambda_context):
        """Test handling of empty command."""
        event = {
            'command': ''
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        # Empty command executes successfully but produces no output
        assert body['result'] is None
        assert body['stdout'] == ''
    
    def test_multiline_code_with_indentation(self, mock_lambda_context):
        """Test execution of properly indented multiline code."""
        event = {
            'command': '''
def calculate(x, y):
    if x > y:
        return x * 2
    else:
        return y * 2

result = calculate(5, 3)
'''
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        assert body['result'] == '10'
    
    def test_exception_during_module_usage(self, mock_lambda_context):
        """Test handling of exceptions when using pre-imported modules."""
        event = {
            'command': '''
# This should cause a ValueError
result = json.loads("not valid json")
'''
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'JSONDecodeError' in body['output'] or 'ValueError' in body['output']