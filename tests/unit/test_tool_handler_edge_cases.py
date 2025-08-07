import pytest
import json
from unittest.mock import Mock, patch
import subprocess
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from tool_handler import handler, execute_cli_command, execute_python_code

class TestToolHandlerEdgeCases:
    """Test edge cases and error scenarios for tool handler."""
    
    def test_cli_command_no_output(self, mock_lambda_context):
        """Test CLI command that completes successfully but produces no output."""
        event = {
            'type': 'cli',
            'command': 'aws sts get-caller-identity'
        }
        
        with patch('tool_handler.subprocess.run') as mock_run:
            # Command succeeds but no stdout
            mock_run.return_value = Mock(
                returncode=0,
                stdout='',
                stderr=''
            )
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
            assert 'Command executed successfully with no output' in body['output']
    
    def test_cli_command_stdout_and_stderr(self, mock_lambda_context):
        """Test CLI command that returns both stdout and stderr."""
        event = {
            'type': 'cli',
            'command': 'aws ec2 describe-instances'
        }
        
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout='Partial data from stdout',
                stderr='Warning: Some deprecation notice'
            )
            
            result = handler(event, mock_lambda_context)
            
            assert result['statusCode'] == 200
            body = json.loads(result['body'])
            assert body['success'] is True
            assert 'Command failed with exit code 1' in body['output']
            assert 'Warning: Some deprecation notice' in body['output']
            assert 'Partial data from stdout' in body['output']
    
    def test_python_code_stdout_restoration_on_exception(self, mock_lambda_context):
        """Test that stdout is restored even when Python execution throws exception."""
        event = {
            'type': 'python',
            'command': 'raise ValueError("Test exception")'
        }
        
        # Verify stdout is restored after exception
        import sys
        original_stdout = sys.stdout
        
        result = handler(event, mock_lambda_context)
        
        # Check stdout was restored
        assert sys.stdout is original_stdout
        
        assert result['statusCode'] == 200  # Handler doesn't fail
        body = json.loads(result['body'])
        assert body['success'] is True
        assert 'Python execution error' in body['output']
        assert 'ValueError: Test exception' in body['output']
    
    def test_execute_cli_command_subprocess_exception(self):
        """Test CLI command execution when subprocess raises unexpected exception."""
        with patch('tool_handler.subprocess.run') as mock_run:
            mock_run.side_effect = OSError("Permission denied")
            
            result = execute_cli_command('aws sts get-caller-identity')
            
            assert 'Failed to execute command' in result
            assert 'Permission denied' in result
    
    def test_execute_python_code_complex_namespace_operations(self):
        """Test Python execution with complex namespace operations."""
        code = """
# Test complex operations with the restricted namespace
import json
data = {'items': [1, 2, 3]}
processed = [item * 2 for item in data['items']]
result = {
    'original': data,
    'processed': processed,
    'summary': f"Processed {len(processed)} items"
}
"""
        result = execute_python_code(code)
        
        # Should handle complex operations correctly
        assert '"original"' in result
        assert '"processed"' in result
        assert '"summary"' in result
        assert 'Processed 3 items' in result
    
    def test_python_code_import_error_handling(self):
        """Test Python code execution when imports fail."""
        code = """
try:
    import nonexistent_module
    result = "Should not reach here"
except ImportError as e:
    result = f"Import failed as expected: {type(e).__name__}"
"""
        result = execute_python_code(code)
        
        assert 'Import failed as expected' in result
        assert 'ModuleNotFoundError' in result
    
    def test_handler_missing_command_field(self, mock_lambda_context):
        """Test handler behavior when command field is missing."""
        event = {
            'type': 'cli'
            # Missing 'command' field
        }
        
        result = handler(event, mock_lambda_context)
        
        # Should handle gracefully
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        # Should execute empty command and likely get an error, but not crash
        assert body['success'] is True
    
    def test_handler_empty_event(self, mock_lambda_context):
        """Test handler with completely empty event."""
        event = {}
        
        result = handler(event, mock_lambda_context)
        
        # Should default to 'cli' type and empty command
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True