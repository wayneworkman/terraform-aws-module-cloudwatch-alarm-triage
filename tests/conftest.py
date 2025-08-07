import pytest
import sys
import os
from unittest.mock import Mock, MagicMock

# Add parent directories to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../lambda')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../tool-lambda')))

@pytest.fixture
def mock_boto3_client():
    """Mock boto3 client for testing."""
    mock_client = MagicMock()
    return mock_client

@pytest.fixture
def sample_alarm_event():
    """Sample CloudWatch Alarm event for testing."""
    return {
        "source": "aws.cloudwatch",
        "accountId": "123456789012",
        "time": "2025-08-06T12:00:00Z",
        "region": "us-east-2",
        "alarmData": {
            "alarmName": "test-lambda-errors",
            "state": {
                "value": "ALARM",
                "reason": "Threshold Crossed: 5 datapoints were greater than the threshold (1.0)",
                "reasonData": "{\"version\":\"1.0\",\"queryDate\":\"2025-08-06T12:00:00.000+0000\"}"
            },
            "previousState": {
                "value": "OK",
                "reason": "Threshold Crossed: 1 datapoint was not greater than the threshold (1.0)"
            },
            "configuration": {
                "metrics": [{
                    "id": "m1",
                    "metricStat": {
                        "metric": {
                            "namespace": "AWS/Lambda",
                            "name": "Errors",
                            "dimensions": {
                                "FunctionName": "test-function"
                            }
                        },
                        "period": 60,
                        "stat": "Sum"
                    }
                }]
            }
        }
    }

@pytest.fixture
def mock_environment():
    """Mock environment variables."""
    env = {
        'BEDROCK_MODEL_ID': 'anthropic.claude-opus-4-1-20250805-v1:0',
        'BEDROCK_AGENT_MODE': 'true',
        'TOOL_LAMBDA_ARN': 'arn:aws:lambda:us-east-2:123456789012:function:tool-lambda',
        'SNS_TOPIC_ARN': 'arn:aws:sns:us-east-2:123456789012:test-topic',
        'INVESTIGATION_DEPTH': 'comprehensive',
        'MAX_TOKENS': '20000',
        'AWS_DEFAULT_REGION': 'us-east-2'
    }
    return env

@pytest.fixture
def mock_lambda_context():
    """Mock Lambda context object."""
    context = Mock()
    context.function_name = 'test-function'
    context.function_version = '$LATEST'
    context.invoked_function_arn = 'arn:aws:lambda:us-east-2:123456789012:function:test-function'
    context.memory_limit_in_mb = '1024'
    context.aws_request_id = 'test-request-id'
    context.log_group_name = '/aws/lambda/test-function'
    context.log_stream_name = '2025/08/06/[$LATEST]test-stream'
    context.get_remaining_time_in_millis = Mock(return_value=300000)
    return context