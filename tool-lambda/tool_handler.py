import json
import subprocess
import boto3
import sys
import os
import traceback
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    try:
        command_type = event.get('type', 'cli')
        command = event.get('command', '')
        
        logger.info(f"Executing {command_type} command: {command[:200]}...")
        
        if command_type == 'cli':
            output = execute_cli_command(command)
            success = True
            
        elif command_type == 'python':
            output = execute_python_code(command)
            success = True
            
        else:
            output = f"Unknown command type: {command_type}. Supported types are 'cli' and 'python'."
            success = False
            logger.error(output)
        
        max_output_size = 50000
        if len(output) > max_output_size:
            output = output[:max_output_size] + "\n\n... Output truncated due to size limit ..."
            logger.warning(f"Output truncated from {len(output)} to {max_output_size} characters")
        
        return {
            'statusCode': 200 if success else 400,
            'body': json.dumps({
                'success': success,
                'output': output,
                'execution_time': datetime.utcnow().isoformat()
            })
        }
        
    except subprocess.TimeoutExpired:
        error_msg = 'Command timed out after 30 seconds'
        logger.error(error_msg)
        return {
            'statusCode': 408,
            'body': json.dumps({
                'success': False,
                'output': error_msg
            })
        }
    except Exception as e:
        error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'output': error_msg[:5000]  # Limit error message size
            })
        }

def execute_cli_command(command):
    """
    Execute AWS CLI command with read-only IAM permissions.
    Security is enforced through IAM policies, not command filtering.
    
    Args:
        command: AWS CLI command to execute
        
    Returns:
        str: Command output or error message
    """
    try:
        # Execute command with timeout
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                'AWS_DEFAULT_REGION': os.environ.get('BEDROCK_REGION'),
                'AWS_PAGER': ''  # Disable pagination for AWS CLI
            }
        )
        
        if result.returncode == 0:
            output = result.stdout
            if not output:
                output = "Command executed successfully with no output"
        else:
            output = f"Command failed with exit code {result.returncode}\n"
            if result.stderr:
                output += f"Error: {result.stderr}"
            if result.stdout:
                output += f"\nOutput: {result.stdout}"
        
        return output
        
    except subprocess.TimeoutExpired:
        raise  # Re-raise to be caught by main handler
    except Exception as e:
        return f"Failed to execute command: {str(e)}"

def execute_python_code(code):
    """
    Execute Python/boto3 code with read-only IAM permissions.
    Security is enforced through IAM policies, not code filtering.
    
    Args:
        code: Python code to execute
        
    Returns:
        str: Execution result or error message
    """
    
    try:
        # Create a restricted namespace for execution
        namespace = {
            'boto3': boto3,
            'json': json,
            'datetime': datetime,
            '__builtins__': {
                'len': len,
                'str': str,
                'int': int,
                'float': float,
                'bool': bool,
                'list': list,
                'dict': dict,
                'tuple': tuple,
                'set': set,
                'print': print,
                'range': range,
                'enumerate': enumerate,
                'zip': zip,
                'map': map,
                'filter': filter,
                'sorted': sorted,
                'min': min,
                'max': max,
                'sum': sum,
                'any': any,
                'all': all,
                'isinstance': isinstance,
                'type': type,
                'Exception': Exception,
                'ValueError': ValueError,
                'ImportError': ImportError,
                'KeyError': KeyError,
                'AttributeError': AttributeError,
                '__import__': __import__,  # Allow safe imports
            },
            'result': None  # Variable to store output
        }
        
        # Capture print output
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        
        try:
            # Execute the Python code
            exec(code, namespace)
            
            # Restore stdout
            sys.stdout = old_stdout
            
            # Get the result
            if namespace.get('result') is not None:
                # Convert result to string, handling different types
                if isinstance(namespace['result'], (dict, list)):
                    output = json.dumps(namespace['result'], indent=2, default=str)
                else:
                    output = str(namespace['result'])
            else:
                # If no result variable was set, use captured print output
                output = captured_output.getvalue()
                if not output:
                    output = "Code executed successfully. Set 'result' variable to return output."
            
            return output
            
        finally:
            # Always restore stdout
            sys.stdout = old_stdout
            
    except Exception as e:
        return f"Python execution error: {str(e)}\n{traceback.format_exc()}"

# For local testing
if __name__ == "__main__":
    # Test CLI command
    test_event_cli = {
        "type": "cli",
        "command": "aws sts get-caller-identity"
    }
    
    # Test Python command
    test_event_python = {
        "type": "python",
        "command": """
import boto3
import json

sts = boto3.client('sts')
identity = sts.get_caller_identity()
result = json.dumps(identity, indent=2, default=str)
"""
    }
    
    print("Testing CLI command:")
    result = handler(test_event_cli, {})
    print(json.dumps(result, indent=2))
    
    print("\nTesting Python command:")
    result = handler(test_event_python, {})
    print(json.dumps(result, indent=2))