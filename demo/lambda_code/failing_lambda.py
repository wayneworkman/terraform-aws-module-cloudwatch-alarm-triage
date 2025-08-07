import boto3
import json
import os
from datetime import datetime

def handler(event, context):
    """
    Attempts to list EC2 instances but will fail due to missing permissions.
    This generates AccessDenied errors that trigger CloudWatch alarms.
    
    The triage system will investigate this failure and identify the missing
    ec2:DescribeInstances permission as the root cause.
    """
    print(f"Demo failing Lambda started at {datetime.utcnow().isoformat()}")
    print(f"Event: {json.dumps(event, default=str)}")
    print(f"Context: Function name: {context.function_name}, Request ID: {context.aws_request_id}")
    print(f"Purpose: {os.environ.get('PURPOSE', 'Demo Lambda')}")
    
    # Initialize EC2 client
    try:
        ec2 = boto3.client('ec2')
        print("EC2 client initialized successfully")
    except Exception as e:
        print(f"Failed to initialize EC2 client: {str(e)}")
        raise
    
    try:
        # This will fail with AccessDeniedException due to missing EC2 permissions
        print("Attempting to describe EC2 instances...")
        response = ec2.describe_instances()
        
        # If we somehow get here (shouldn't happen with restricted permissions)
        reservations = response.get('Reservations', [])
        instance_count = sum(len(reservation.get('Instances', [])) for reservation in reservations)
        
        success_message = f"SUCCESS: Found {len(reservations)} reservations with {instance_count} total instances"
        print(success_message)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': success_message,
                'reservations': len(reservations),
                'instances': instance_count,
                'timestamp': datetime.utcnow().isoformat()
            })
        }
        
    except Exception as e:
        error_message = f"EXPECTED FAILURE: {str(e)}"
        print(f"ERROR: {error_message}")
        
        # Log additional context for Claude's investigation
        print("Additional context for investigation:")
        print(f"  - Lambda function name: {context.function_name}")
        print(f"  - Lambda function ARN: {context.invoked_function_arn}")
        print(f"  - AWS region: {os.environ.get('AWS_DEFAULT_REGION', 'unknown')}")
        print(f"  - Request ID: {context.aws_request_id}")
        print(f"  - Memory limit: {context.memory_limit_in_mb}MB")
        print(f"  - Time remaining: {context.get_remaining_time_in_millis()}ms")
        
        # Re-raise to ensure Lambda invocation fails (triggering the alarm)
        raise Exception(error_message)