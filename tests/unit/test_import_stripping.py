"""
Test import statement stripping functionality in tool_handler.
"""
import pytest
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../tool-lambda')))

from tool_handler import remove_imports, execute_python_code, handler

class TestImportStripping:
    """Test the automatic import statement removal feature."""
    
    def test_remove_simple_imports(self):
        """Test removal of simple import statements."""
        code = """
import json
import boto3
import os

result = "test"
"""
        cleaned, removed = remove_imports(code)
        
        assert 'import json' not in cleaned
        assert 'import boto3' not in cleaned
        assert 'import os' not in cleaned
        assert 'result = ' in cleaned and 'test' in cleaned
        
        assert 'import json' in removed
        assert 'import boto3' in removed
        assert 'import os' in removed
        assert len(removed) == 3
    
    def test_remove_from_imports(self):
        """Test removal of from...import statements."""
        code = """
from datetime import datetime, timedelta
from os import path
from collections import defaultdict

data = defaultdict(list)
"""
        cleaned, removed = remove_imports(code)
        
        assert 'from datetime' not in cleaned
        assert 'from os' not in cleaned
        assert 'from collections' not in cleaned
        assert 'data = defaultdict(list)' in cleaned
        
        assert 'from datetime import datetime' in removed
        assert 'from datetime import timedelta' in removed
        assert 'from os import path' in removed
        assert 'from collections import defaultdict' in removed
    
    def test_remove_aliased_imports(self):
        """Test removal of aliased imports."""
        code = """
import numpy as np
import pandas as pd
from datetime import datetime as dt

result = "processed"
"""
        cleaned, removed = remove_imports(code)
        
        assert 'import numpy' not in cleaned
        assert 'import pandas' not in cleaned
        assert 'from datetime' not in cleaned
        assert 'result = ' in cleaned and 'processed' in cleaned
        
        assert 'import numpy' in removed
        assert 'import pandas' in removed
        assert 'from datetime import datetime' in removed
    
    def test_execute_with_imports_removed(self):
        """Test that code executes successfully after import removal."""
        code = """
import boto3
import json
import datetime

# This would normally fail if imports weren't pre-imported
sts = boto3.client('sts')
now = datetime.datetime.now()
data = json.dumps({"time": str(now)})
result = f"Data: {data[:20]}"
"""
        result_dict = execute_python_code(code)
        
        assert result_dict['success'] is True
        assert 'Data:' in result_dict['result']
        assert 'Removed 3 import statement(s)' in result_dict['stdout']
        assert 'import boto3' in result_dict['stdout']
        assert 'import json' in result_dict['stdout']
        assert 'import datetime' in result_dict['stdout']
    
    def test_handler_with_imports(self, mock_lambda_context):
        """Test Lambda handler with code containing imports."""
        event = {
            'command': """
import boto3
import json

# Get caller identity
sts = boto3.client('sts')
identity = {"account": "123456789012", "arn": "test-arn"}
result = json.dumps(identity)
"""
        }
        
        response = handler(event, mock_lambda_context)
        
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['success'] is True
        
        # Check that import removal was noted
        assert 'Removed 2 import statement(s)' in body['stdout']
        assert 'import boto3' in body['stdout']
        assert 'import json' in body['stdout']
        
        # Check that code still executed
        assert 'test-arn' in body['result']
    
    def test_syntax_error_handling(self):
        """Test handling of syntax errors during import removal."""
        code = """
import json
this is not valid python syntax!!!
"""
        cleaned, removed = remove_imports(code)
        
        # Should return original code when there's a syntax error
        assert cleaned == code
        assert len(removed) == 0
    
    def test_complex_import_patterns(self):
        """Test removal of complex import patterns."""
        code = """
import sys
from os.path import join, exists
from collections.abc import Mapping
import urllib.parse
from . import relative_module
from ..parent import something

# Actual code
result = "complex imports handled"
"""
        cleaned, removed = remove_imports(code)
        
        assert 'import sys' not in cleaned
        assert 'from os.path' not in cleaned
        assert 'from collections.abc' not in cleaned
        assert 'import urllib.parse' not in cleaned
        assert 'from .' not in cleaned
        assert 'result = ' in cleaned and 'complex imports handled' in cleaned
        
        # Check that all imports were tracked
        assert len(removed) >= 6
    
    def test_multiline_imports(self):
        """Test removal of multiline import statements."""
        code = """
from datetime import (
    datetime,
    timedelta,
    timezone
)

result = "multiline import handled"
"""
        cleaned, removed = remove_imports(code)
        
        assert 'from datetime' not in cleaned
        assert 'datetime,' not in cleaned
        assert 'timedelta,' not in cleaned
        assert 'timezone' not in cleaned
        assert 'result = ' in cleaned and 'multiline import handled' in cleaned
        
        # Should track each imported item
        assert 'from datetime import datetime' in removed
        assert 'from datetime import timedelta' in removed
        assert 'from datetime import timezone' in removed
    
    def test_import_after_code(self):
        """Test that imports anywhere in the code are removed."""
        code = """
result = []

import json
result.append("first")

import boto3
result.append("second")

from datetime import datetime
result.append("third")

result = ", ".join(result)
"""
        cleaned, removed = remove_imports(code)
        
        assert 'import json' not in cleaned
        assert 'import boto3' not in cleaned
        assert 'from datetime' not in cleaned
        
        # Code structure should be preserved
        assert 'result = []' in cleaned
        assert 'result.append(' in cleaned and 'first' in cleaned
        assert 'result.append(' in cleaned and 'second' in cleaned
        assert 'result.append(' in cleaned and 'third' in cleaned
        
        assert len(removed) == 3
    
    def test_no_imports_to_remove(self):
        """Test code without any imports."""
        code = """
# Pure Python code without imports
x = 5
y = 10
result = x + y
"""
        cleaned, removed = remove_imports(code)
        
        # ast.unparse may remove comments, so just check core content
        assert 'x = 5' in cleaned
        assert 'y = 10' in cleaned
        assert 'result = x + y' in cleaned
        assert len(removed) == 0
    
    def test_import_removal_performance(self):
        """Test that import removal doesn't significantly impact performance."""
        import time
        
        # Large code with many imports
        code = "\n".join([
            "import module" + str(i) for i in range(100)
        ]) + "\n\nresult = 'performance test'"
        
        start = time.time()
        cleaned, removed = remove_imports(code)
        duration = time.time() - start
        
        # Should process even 100 imports quickly
        assert duration < 0.1  # Less than 100ms
        assert len(removed) == 100
        assert 'result = \'performance test\'' in cleaned