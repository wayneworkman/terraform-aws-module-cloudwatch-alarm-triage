#!/usr/bin/env python3
"""
Script to fix all failing tests after the changes made for enhanced visibility and logging.
The main changes that broke tests are:
1. BedrockAgentClient.investigate_with_tools now returns a dict instead of a string
2. Logging levels changed from warning to debug for many messages
"""

import os
import re
import sys

def fix_file(filepath, fixes):
    """Apply a list of fixes to a file."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original = content
    for old, new in fixes:
        content = content.replace(old, new)
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed: {filepath}")
        return True
    return False

def main():
    fixes_applied = 0
    
    # Fix test_trailing_tool_cleanup.py - change warning assertions to debug
    trailing_tool_fixes = [
        ('mock_logger.warning.assert_called()', 'mock_logger.debug.assert_called()'),
        ('warning_call = mock_logger.warning.call_args[0][0]', 'debug_call = mock_logger.debug.call_args[0][0]'),
        ('assert "Removed trailing tool call" in warning_call', 'assert "Removed trailing tool call" in debug_call'),
        ('assert "original:" in warning_call', 'assert "original:" in debug_call'),
        ('assert "cleaned:" in warning_call', 'assert "cleaned:" in debug_call'),
    ]
    
    if fix_file('tests/unit/test_trailing_tool_cleanup.py', trailing_tool_fixes):
        fixes_applied += 1
    
    # Fix tests that expect string results to expect dict results
    test_files = [
        'tests/unit/test_bedrock_client_edge_cases.py',
        'tests/unit/test_complex_interactions.py',
        'tests/unit/test_iteration2_integration_points.py',
        'tests/unit/test_iteration3_production_readiness.py',
        'tests/unit/test_monitoring_and_observability.py',
        'tests/unit/test_performance_and_load.py',
        'tests/unit/test_performance_scenarios.py',
        'tests/unit/test_production_readiness.py',
        'tests/unit/test_resource_limits_and_scaling.py',
        'tests/unit/test_security_boundaries.py',
    ]
    
    # Common patterns to fix for dict return type
    dict_fixes = [
        # When checking the result directly as a string
        ('assert "Investigation complete" in result', 
         'assert isinstance(result, dict) and "Investigation complete" in result.get("report", result)'),
        ('assert "analysis" in result.lower()', 
         'assert isinstance(result, dict) and "analysis" in result.get("report", "").lower()'),
        ('assert len(result) > 100', 
         'assert isinstance(result, dict) and len(result.get("report", "")) > 100'),
        # Mock return values that should be dicts
        ('mock_bedrock_instance.investigate_with_tools.return_value = "Test analysis"',
         'mock_bedrock_instance.investigate_with_tools.return_value = {"report": "Test analysis", "full_context": [], "iteration_count": 1, "tool_calls": []}'),
    ]
    
    for filepath in test_files:
        if os.path.exists(filepath):
            if fix_file(filepath, dict_fixes):
                fixes_applied += 1
    
    # Special handling for tests that check logger.warning for retry messages
    retry_log_fixes = [
        ('assert any("retrying" in str(call).lower() for call in mock_logger.warning.call_args_list)',
         'assert any("retrying" in str(call).lower() for call in mock_logger.info.call_args_list)'),
        ('mock_logger.warning.assert_any_call',
         'mock_logger.info.assert_any_call'),
    ]
    
    for filepath in test_files:
        if os.path.exists(filepath):
            if fix_file(filepath, retry_log_fixes):
                fixes_applied += 1
    
    print(f"\nTotal files fixed: {fixes_applied}")
    
    # Now let's create a more comprehensive fix
    print("\nApplying comprehensive fixes...")
    
    # Read each test file and apply intelligent fixes
    for filepath in test_files:
        if not os.path.exists(filepath):
            continue
            
        with open(filepath, 'r') as f:
            content = f.read()
        
        original = content
        
        # Fix assertions that expect string results
        content = re.sub(
            r'assert result == (["\'])(.*?)\1',
            r'assert isinstance(result, dict) and result.get("report", "") == \1\2\1',
            content
        )
        
        # Fix assertions checking if something is in result
        content = re.sub(
            r'assert (["\'])(.*?)\1 in result(?!\[)',
            r'assert isinstance(result, dict) and \1\2\1 in result.get("report", "")',
            content
        )
        
        # Fix mock return values
        content = re.sub(
            r'investigate_with_tools\.return_value = (["\'])(.*?)\1',
            r'investigate_with_tools.return_value = {"report": \1\2\1, "full_context": [], "iteration_count": 1, "tool_calls": []}',
            content
        )
        
        if content != original:
            with open(filepath, 'w') as f:
                f.write(content)
            print(f"Applied regex fixes to: {filepath}")

if __name__ == '__main__':
    main()