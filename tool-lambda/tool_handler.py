import json
import boto3
import sys
import os
import traceback
import logging
from datetime import datetime, timedelta
import re
import base64
import ipaddress
import collections
import time
import hashlib
import urllib
import itertools
import functools
import csv
import math
import random
import operator
import statistics
import decimal
import fractions
import string
import textwrap
import difflib
import fnmatch
import glob
import copy
import pprint
import enum
import dataclasses
import typing
import uuid
import platform
import warnings
import gzip
import zlib
import tarfile
import zipfile
import ast
from io import StringIO, BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """Main Lambda handler for executing Python code with pre-imported modules."""
    try:
        # Execute Python code
        command = event.get('command', '')
        
        logger.info(f"Executing Python code: {command[:200]}...")
        
        execution_result = execute_python_code(command)
        
        # Maintain backward compatibility by including 'output' field
        # Combine all outputs for backward compatibility
        combined_output = ""
        if execution_result['stdout']:
            combined_output += execution_result['stdout']
        if execution_result['stderr']:
            if combined_output:
                combined_output += "\n"
            combined_output += f"[STDERR]\n{execution_result['stderr']}"
        if execution_result['result']:
            if combined_output and not combined_output.strip().endswith('\n'):
                combined_output += "\n"
            combined_output += execution_result['result']
        
        return {
            'statusCode': 200,  # Always return 200 for controlled errors (success flag indicates actual status)
            'body': json.dumps({
                'success': execution_result['success'],
                'output': combined_output,  # Backward compatibility
                'result': execution_result['result'],
                'stdout': execution_result['stdout'],
                'stderr': execution_result['stderr'],
                'execution_time': execution_result['execution_time']
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


def remove_imports(code):
    """
    Remove all import statements from Python code to enable compatibility
    with models that include imports despite instructions.
    
    Args:
        code: Python code potentially containing import statements
        
    Returns:
        tuple: (cleaned_code, list_of_removed_imports)
    """
    try:
        tree = ast.parse(code)
        removed_imports = []
        
        # Collect import statements for logging
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    removed_imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    if node.level > 0:
                        removed_imports.append(f"from {'.' * node.level}{module} import {alias.name}")
                    else:
                        removed_imports.append(f"from {module} import {alias.name}")
        
        # Keep only non-import statements
        tree.body = [node for node in tree.body 
                    if not isinstance(node, (ast.Import, ast.ImportFrom))]
        
        # Return cleaned code and list of removed imports
        cleaned_code = ast.unparse(tree)
        return cleaned_code, removed_imports
    except SyntaxError as e:
        # If there's a syntax error, return original code
        logger.warning(f"Syntax error while removing imports: {e}")
        return code, []

def execute_python_code(code):
    """
    Execute Python/boto3 code with read-only IAM permissions.
    Security is enforced through IAM policies, not code filtering.
    Automatically removes import statements for compatibility with various AI models.
    
    Args:
        code: Python code to execute
        
    Returns:
        dict: Execution results including stdout, stderr, result, and timing
    """
    
    start_time = time.time()
    
    # Remove import statements for compatibility with models that include them
    cleaned_code, removed_imports = remove_imports(code)
    
    # Log removed imports to stdout if any were found
    import_notice = ""
    if removed_imports:
        import_notice = f"Note: Removed {len(removed_imports)} import statement(s) for compatibility:\n"
        for imp in removed_imports:
            import_notice += f"  - {imp}\n"
        import_notice += "All required modules are pre-imported.\n\n"
        logger.info(f"Removed {len(removed_imports)} import statements from code")
    
    # Import StringIO here for output capture
    from io import StringIO as StringIO_capture
    
    try:
        # Create a namespace with all the pre-imported modules
        namespace = {
            # Core modules
            'boto3': boto3,
            'json': json,
            'datetime': datetime,
            'timedelta': timedelta,
            
            # Additional standard library modules
            're': re,
            'base64': base64,
            'ipaddress': ipaddress,
            'collections': collections,
            'time': time,
            'hashlib': hashlib,
            'urllib': urllib,
            'itertools': itertools,
            'functools': functools,
            'csv': csv,
            'math': math,
            'random': random,
            'os': os,  # Limited to safe operations by Lambda environment
            'operator': operator,
            'statistics': statistics,
            'decimal': decimal,
            'fractions': fractions,
            'string': string,
            'textwrap': textwrap,
            'difflib': difflib,
            'fnmatch': fnmatch,
            'glob': glob,
            'copy': copy,
            'pprint': pprint,
            'enum': enum,
            'dataclasses': dataclasses,
            'typing': typing,
            'uuid': uuid,
            'sys': sys,
            'platform': platform,
            'traceback': traceback,
            'warnings': warnings,
            'gzip': gzip,
            'zlib': zlib,
            'tarfile': tarfile,
            'zipfile': zipfile,
            'StringIO': StringIO,
            'BytesIO': BytesIO,
            
            # Safe builtins
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
                'frozenset': frozenset,
                'print': print,
                'range': range,
                'enumerate': enumerate,
                'zip': zip,
                'map': map,
                'filter': filter,
                'sorted': sorted,
                'reversed': reversed,
                'min': min,
                'max': max,
                'sum': sum,
                'any': any,
                'all': all,
                'abs': abs,
                'round': round,
                'isinstance': isinstance,
                'issubclass': issubclass,
                'type': type,
                'dir': dir,
                'getattr': getattr,
                'hasattr': hasattr,
                'setattr': setattr,
                'callable': callable,
                'format': format,
                'repr': repr,
                'locals': locals,
                'globals': globals,
                'ascii': ascii,
                'bin': bin,
                'hex': hex,
                'oct': oct,
                'ord': ord,
                'chr': chr,
                'divmod': divmod,
                'pow': pow,
                'slice': slice,
                'bytes': bytes,
                'bytearray': bytearray,
                'memoryview': memoryview,
                'open': open,  # Limited by Lambda environment
                'Exception': Exception,
                'ValueError': ValueError,
                'TypeError': TypeError,
                'ImportError': ImportError,
                'KeyError': KeyError,
                'IndexError': IndexError,
                'AttributeError': AttributeError,
                'RuntimeError': RuntimeError,
                'StopIteration': StopIteration,
                'GeneratorExit': GeneratorExit,
                'SystemExit': SystemExit,
                'KeyboardInterrupt': KeyboardInterrupt,
                'MemoryError': MemoryError,
                'NameError': NameError,
                'NotImplementedError': NotImplementedError,
                'OSError': OSError,
                'OverflowError': OverflowError,
                'RecursionError': RecursionError,
                'ReferenceError': ReferenceError,
                'SyntaxError': SyntaxError,
                'SystemError': SystemError,
                'TabError': TabError,
                'TimeoutError': TimeoutError,
                'UnicodeError': UnicodeError,
                'UserWarning': UserWarning,
                'DeprecationWarning': DeprecationWarning,
                'PendingDeprecationWarning': PendingDeprecationWarning,
                'SyntaxWarning': SyntaxWarning,
                'RuntimeWarning': RuntimeWarning,
                'FutureWarning': FutureWarning,
                'ImportWarning': ImportWarning,
                'UnicodeWarning': UnicodeWarning,
                'BytesWarning': BytesWarning,
                'ResourceWarning': ResourceWarning,
                '__import__': __import__,  # Allow imports since modules are pre-imported
                '__build_class__': __build_class__,  # Allow class definitions
                '__name__': '__main__',  # Module name for class definitions
                'True': True,
                'False': False,
                'None': None,
            },
            'result': None  # Variable to store output
        }
        
        # Capture print output and errors
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_stdout = StringIO_capture()
        captured_stderr = StringIO_capture()
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        
        try:
            # Execute the cleaned Python code
            exec(cleaned_code, namespace)
            
            # Restore stdout and stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            
            execution_time = time.time() - start_time
            
            # Get the result variable if set
            result_value = namespace.get('result')
            
            # Convert result to appropriate format
            if result_value is not None:
                if isinstance(result_value, (dict, list)):
                    result_str = json.dumps(result_value, indent=2, default=str)
                else:
                    result_str = str(result_value)
            else:
                result_str = None
            
            # Return structured response
            return {
                'result': result_str,
                'stdout': import_notice + captured_stdout.getvalue(),
                'stderr': captured_stderr.getvalue(),
                'execution_time': execution_time,
                'success': True
            }
            
        finally:
            # Always restore stdout and stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            
    except Exception as e:
        execution_time = time.time() - start_time
        
        # Prepare error message
        if "__import__" in str(e) and "not found" in str(e):
            error_msg = f"Error executing Python code: {str(e)}\nNote: Modules are pre-imported. You don't need to use import statements. Use the modules directly (e.g., boto3.client('s3') instead of 'import boto3')."
        else:
            error_msg = f"Error executing Python code: {str(e)}\nTraceback (most recent call last):\n{traceback.format_exc()}"
        
        # Try to get any captured output before the error
        stdout_output = ""
        stderr_output = ""
        try:
            stdout_output = captured_stdout.getvalue()
        except:
            pass
        try:
            stderr_output = captured_stderr.getvalue()
        except:
            pass
        
        return {
            'result': None,
            'stdout': import_notice + stdout_output,
            'stderr': stderr_output + error_msg,
            'execution_time': execution_time,
            'success': False
        }

# Alias for compatibility
handler = lambda_handler

# For local testing
if __name__ == "__main__":
    # Test Python command
    test_event = {
        "command": """
# No imports needed - modules are pre-imported
sts = boto3.client('sts')
identity = sts.get_caller_identity()
result = json.dumps(identity, indent=2, default=str)
"""
    }
    
    print("Testing Python code execution:")
    result = lambda_handler(test_event, {})
    print(json.dumps(result, indent=2))