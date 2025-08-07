#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'lambda')))

from prompt_template import PromptTemplate

# Complex alarm event with nested structures and special characters
complex_alarm = {
    'alarmData': {
        'alarmName': 'complex-alarm-with-special-chars-éáñ',
        'state': {'value': 'ALARM', 'reason': 'Threshold "crossed" & limit exceeded'},
        'configuration': {
            'metrics': [
                {
                    'name': 'CPUUtilization',
                    'dimensions': {'InstanceId': 'i-1234567890abcdef0'},
                    'statistics': ['Average', 'Maximum']
                }
            ],
            'thresholds': [80.0, 90.0, 95.0],
            'tags': {'Environment': 'prod/staging', 'Team': 'ops & devs'}
        }
    },
    'region': 'us-east-1',
    'accountId': '123456789012',
    'time': '2025-01-15T10:30:00.000Z',
    'metadata': {
        'unicode': '测试数据',
        'nested': {'deep': {'value': 'very deep'}},
        'array': [1, 2, {'key': 'value'}, None, True]
    }
}

prompt = PromptTemplate.generate_investigation_prompt(
    alarm_event=complex_alarm,
    investigation_depth='comprehensive'
)

print("=== PROMPT GENERATED ===")
print(prompt)
print("=== END PROMPT ===")

# Check if our test strings are in the prompt
test_strings = [
    'complex-alarm-with-special-chars-éáñ',
    'Threshold "crossed" & limit exceeded',
    '测试数据',
    'alarmData'
]

print("\n=== STRING SEARCH RESULTS ===")
for test_str in test_strings:
    found = test_str in prompt
    print(f"'{test_str}' found: {found}")
    
    if not found:
        # Look for escaped versions
        escaped_versions = [
            test_str.replace('"', '\\"'),
            test_str.replace('"', '\\\"'),
            repr(test_str)[1:-1],  # Python string representation
        ]
        
        for escaped in escaped_versions:
            if escaped in prompt:
                print(f"  Found escaped version: '{escaped}'")
                break