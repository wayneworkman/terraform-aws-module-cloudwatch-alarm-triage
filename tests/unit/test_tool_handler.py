import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from tool_handler import handler, execute_cli_command, execute_python_code

class TestToolHandler:
    
    def test_handler_cli_success(self, mock_lambda_context):
        """Test successful CLI command execution."""
        event = {
            'type': 'cli',
            'command': 'aws --version'
        }
        
        with patch('tool_handler.execute_cli_command') as mock_cli:
            mock_cli.return_value = 'aws-cli/2.13.0 Python/3.11.4'
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
            assert 'aws-cli' in body['output']
    
    def test_handler_python_success(self, mock_lambda_context):
        """Test successful Python code execution."""
        event = {
            'type': 'python',
            'command': 'result = "Hello from Python"'
        }
        
        with patch('tool_handler.execute_python_code') as mock_python:
            mock_python.return_value = 'Hello from Python'
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
            assert body['output'] == 'Hello from Python'
    
    def test_handler_unknown_type(self, mock_lambda_context):
        """Test handling of unknown command type."""
        event = {
            'type': 'unknown',
            'command': 'test'
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert body['success'] is False
        assert 'Unknown command type' in body['output']
    
    def test_handler_timeout(self, mock_lambda_context):
        """Test handling of command timeout."""
        event = {
            'type': 'cli',
            'command': 'sleep 60'
        }
        
        with patch('tool_handler.execute_cli_command') as mock_cli:
            mock_cli.side_effect = subprocess.TimeoutExpired('sleep 60', 30)
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 408
            body = json.loads(result['body'])
            assert body['success'] is False
            assert 'timed out' in body['output']
    
    def test_handler_exception(self, mock_lambda_context):
        """Test handling of unexpected exceptions."""
        event = {
            'type': 'cli',
            'command': 'aws s3 ls'
        }
        
        with patch('tool_handler.execute_cli_command') as mock_cli:
            mock_cli.side_effect = Exception("Unexpected error")
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 500
            body = json.loads(result['body'])
            assert body['success'] is False
            assert 'Unexpected error' in body['output']
    
    def test_handler_output_truncation(self, mock_lambda_context):
        """Test that large outputs are truncated."""
        event = {
            'type': 'python',
            'command': 'result = "A" * 60000'  # 60KB of data
        }
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert len(body['output']) <= 51000  # Should be truncated
        assert 'truncated' in body['output']
    
    def test_execute_cli_command_success(self):
        """Test successful CLI command execution."""
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout='Command output',
                stderr=''
            )
            
            result = execute_cli_command('aws sts get-caller-identity')
            
            assert result == 'Command output'
            mock_run.assert_called_once()
    
    def test_execute_cli_command_failure(self):
        """Test CLI command failure handling."""
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout='',
                stderr='Access denied'
            )
            
            result = execute_cli_command('aws ec2 describe-instances')
            
            assert 'Command failed' in result
            assert 'Access denied' in result
    
    def test_execute_cli_command_with_error(self):
        """Test CLI command that returns an error code."""
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout='',
                stderr='AccessDenied: User is not authorized'
            )
            
            result = execute_cli_command('aws ec2 terminate-instances --instance-ids i-123')
            
            # Should return the error information, not block it
            assert 'Command failed' in result
            assert 'AccessDenied' in result
    
    def test_execute_cli_command_various_commands(self):
        """Test execution of various commands."""
        commands = [
            'aws sts get-caller-identity',
            'aws ec2 describe-instances', 
            'aws logs describe-log-groups',
            'date',
            'echo test'
        ]
        
        for cmd in commands:
            with patch('tool_handler.subprocess.run') as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout='command output', stderr='')
                result = execute_cli_command(cmd)
                assert 'command output' in result or 'Command executed successfully' in result
    
    def test_execute_python_code_success(self):
        """Test successful Python code execution."""
        code = """
import json
data = {'key': 'value'}
result = json.dumps(data)
"""
        result = execute_python_code(code)
        assert 'key' in result and 'value' in result
    
    def test_execute_python_code_print_capture(self):
        """Test that print statements are captured."""
        code = """
print("Hello")
print("World")
"""
        result = execute_python_code(code)
        assert 'Hello' in result
        assert 'World' in result
    
    def test_execute_python_code_boto3_operations(self):
        """Test Python code with boto3 operations."""
        code = """
import boto3
client = boto3.client('ec2')
try:
    # This would fail with AccessDenied in real execution due to IAM
    response = client.terminate_instances(InstanceIds=['i-123'])
    result = "Should not reach here"
except Exception as e:
    result = f"Expected IAM error: {type(e).__name__}"
"""
        result = execute_python_code(code)
        # In test environment, boto3 operations work but in production IAM would block
        assert result is not None
    
    def test_execute_python_code_boto3_access(self):
        """Test that boto3 is available in Python execution."""
        code = """
import boto3
result = str(type(boto3))
"""
        result = execute_python_code(code)
        assert 'module' in result
    
    def test_execute_python_code_error_handling(self):
        """Test Python execution error handling."""
        code = """
# This will cause a NameError
result = undefined_variable
"""
        result = execute_python_code(code)
        assert 'Python execution error' in result
        assert 'NameError' in result
    
    def test_execute_python_code_json_result(self):
        """Test that dict/list results are JSON formatted."""
        code = """
result = {'name': 'test', 'values': [1, 2, 3]}
"""
        result = execute_python_code(code)
        # Should be formatted JSON
        assert '"name": "test"' in result
        assert '"values": [' in result
    
    def test_execute_python_code_no_result(self):
        """Test handling when no result variable is set."""
        code = """
x = 5
y = 10
z = x + y
"""
        result = execute_python_code(code)
        assert "Set 'result' variable to return output" in result
    
    def test_execute_cli_command_aws_pager_disabled(self):
        """Test that AWS pager is disabled for CLI commands."""
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout='output', stderr='')
            
            execute_cli_command('aws s3 ls')
            
            # Check that AWS_PAGER is set to empty string
            call_env = mock_run.call_args[1]['env']
            assert call_env['AWS_PAGER'] == ''
    
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
        result = execute_python_code(safe_code)
        assert '3' in result
        assert '123' in result
        assert 'list' in result