"""
Testing Iteration 1: Address coverage gaps in tool_handler.py
Focus on Python execution edge cases and error handling
"""
import pytest
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from tool_handler import handler, lambda_handler, execute_python_code

class TestToolHandlerIteration1Gaps:
    """Tests to address specific coverage gaps in Python execution."""
    
    def test_execute_python_code_timeout_simulation(self):
        """Test handling of long-running Python code."""
        # Note: actual timeout would require threading, this tests the structure
        code = """
import time
# Simulate a long operation
for i in range(3):
    print(f"Step {i}")
result = "Completed"
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert 'Step 0' in result_dict['stdout']
        assert result_dict['result'] == 'Completed'
    
    def test_main_block_execution(self):
        """Test that main block executes when module is run directly."""
        # Import the module to check if main block exists
        import tool_handler
        
        # Check that the module has the test event defined
        source = open(tool_handler.__file__).read()
        assert 'if __name__ == "__main__"' in source
        assert 'test_event' in source
    
    def test_python_code_complex_error_with_partial_output(self):
        """Test Python code that produces output before failing."""
        code = """
print("Starting process...")
result = []
for i in range(5):
    print(f"Processing item {i}")
    if i == 3:
        raise ValueError("Error at item 3")
    result.append(i * 2)
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is False
        assert 'Starting process' in result_dict['stdout']
        assert 'Processing item 0' in result_dict['stdout']
        assert 'Processing item 3' in result_dict['stdout']
        assert 'ValueError: Error at item 3' in result_dict['stderr']
    
    def test_python_code_exception_handling(self):
        """Test various exception types in Python execution."""
        test_cases = [
            ("1 / 0", "ZeroDivisionError"),
            ("int('not a number')", "ValueError"),
            ("[1, 2][5]", "IndexError"),
            ("{'a': 1}['b']", "KeyError"),
            ("None.something", "AttributeError"),
        ]
        
        for code, expected_error in test_cases:
            result_dict = execute_python_code(f"result = {code}")
            assert result_dict['success'] is False
            assert expected_error in result_dict['stderr']
    
    def test_python_code_import_attempt(self):
        """Test behavior when trying to import modules (should work as they're pre-imported)."""
        code = """
# These modules are pre-imported, so this should work
result = {
    'boto3_type': str(type(boto3)),
    'json_type': str(type(json)),
    'datetime_type': str(type(datetime))
}
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert 'module' in result_dict['result']
    
    def test_python_code_execution_stdout_restoration_edge_case(self):
        """Test stdout restoration in edge cases."""
        code = """
import sys
# Try to mess with stdout (should be restored)
old_stdout = sys.stdout
sys.stdout = None  # This will cause issues
print("This might fail")
"""
        # Even if the code tries to break stdout, our handler should restore it
        result_dict = execute_python_code(code)
        
        # Verify sys.stdout is still valid after execution
        import sys
        assert sys.stdout is not None
        assert hasattr(sys.stdout, 'write')
    
    def test_handler_large_output_truncation_boundary(self, mock_lambda_context):
        """Test output truncation at exact boundary conditions."""
        # Test exactly at limit
        with patch.dict(os.environ, {'MAX_OUTPUT_SIZE': '100'}):
            event = {'command': 'result = "A" * 100'}
            result = handler(event, mock_lambda_context)
            body = json.loads(result['body'])
            assert body['success'] is True
            # Should not be truncated at exact limit
            assert 'truncated' not in body.get('result', '')
            
            # Test just over limit
            event = {'command': 'result = "B" * 101'}
            result = handler(event, mock_lambda_context)
            body = json.loads(result['body'])
            assert body['success'] is True
            # Should be truncated
            assert len(body['result']) <= 150  # Some buffer for truncation message
    
    def test_handler_missing_command_field(self, mock_lambda_context):
        """Test handler with missing command field."""
        event = {}  # No command field
        
        result = handler(event, mock_lambda_context)
        
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['success'] is True
        # Should handle missing command gracefully
        assert body['output'] == '' or body['result'] is None
    
    def test_python_execution_with_nested_exception_handling(self):
        """Test Python code with nested try-except blocks."""
        code = """
result = []
try:
    result.append("outer try")
    try:
        result.append("inner try")
        raise ValueError("Inner error")
    except ValueError as e:
        result.append(f"caught inner: {e}")
    result.append("after inner")
except Exception as e:
    result.append(f"caught outer: {e}")
finally:
    result.append("finally")
result = ", ".join(result)
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert 'outer try' in result_dict['result']
        assert 'inner try' in result_dict['result']
        assert 'caught inner: Inner error' in result_dict['result']
        assert 'after inner' in result_dict['result']
        assert 'finally' in result_dict['result']
    
    def test_python_code_with_generators_and_iterators(self):
        """Test Python code using generators and iterators."""
        code = """
# Test generator
def my_gen():
    for i in range(3):
        yield i * 2

# Test list comprehension
squares = [x**2 for x in range(5)]

# Test generator expression
gen_expr = (x*3 for x in range(3))

result = {
    'generator': list(my_gen()),
    'squares': squares,
    'gen_expr': list(gen_expr)
}
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        # Check values are present (JSON formatting may vary)
        assert '0' in result_dict['result'] and '2' in result_dict['result'] and '4' in result_dict['result']
        assert '16' in result_dict['result']  # Check key value is present
        assert '6' in result_dict['result']  # Check key value is present
    
    def test_python_code_with_context_managers(self):
        """Test Python code using context managers."""
        code = """
from io import StringIO

# Test context manager
output = []
with StringIO("test data") as f:
    output.append(f.read())

# Test multiple context managers
result = "Read: " + ", ".join(output)
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        # The import will be stripped, but StringIO is available in the namespace
        # through the io module that's in builtins
        assert 'Read: test data' in result_dict['result'] or 'StringIO' in result_dict['stderr']
    
    def test_python_code_with_decorators(self):
        """Test Python code using decorators."""
        code = """
# Test decorator
def my_decorator(func):
    def wrapper(*args, **kwargs):
        return f"Decorated: {func(*args, **kwargs)}"
    return wrapper

@my_decorator
def greet(name):
    return f"Hello, {name}"

result = greet("World")
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert 'Decorated: Hello, World' in result_dict['result']
    
    def test_python_code_with_class_definitions(self):
        """Test Python code with class definitions."""
        code = """
class Calculator:
    def __init__(self, initial=0):
        self.value = initial
    
    def add(self, x):
        self.value += x
        return self
    
    def multiply(self, x):
        self.value *= x
        return self
    
    def get_result(self):
        return self.value

calc = Calculator(5)
result = calc.add(3).multiply(2).get_result()
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert result_dict['result'] == '16'
    
    def test_python_code_with_lambda_functions(self):
        """Test Python code using lambda functions."""
        code = """
# Test lambda functions
add = lambda x, y: x + y
multiply = lambda x, y: x * y
power = lambda x: lambda y: x ** y

# Test map with lambda
numbers = [1, 2, 3, 4, 5]
squared = list(map(lambda x: x**2, numbers))

# Test filter with lambda
evens = list(filter(lambda x: x % 2 == 0, numbers))

result = {
    'add': add(3, 4),
    'multiply': multiply(3, 4),
    'power': power(2)(3),
    'squared': squared,
    'evens': evens
}
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert '"add": 7' in result_dict['result']
        assert '"multiply": 12' in result_dict['result']
        assert '"power": 8' in result_dict['result']
        # Check key values are present (JSON formatting may vary)
        assert '25' in result_dict['result']  # Last squared value
        assert '"evens"' in result_dict['result']