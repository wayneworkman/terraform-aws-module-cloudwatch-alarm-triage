import json
import os
import boto3
import logging
import time
from decimal import Decimal
from bedrock_client import BedrockAgentClient
from prompt_template import PromptTemplate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def should_investigate(alarm_name, investigation_window_hours=None):
    try:
        region = os.environ.get('BEDROCK_REGION', 'us-east-1')
        dynamodb = boto3.resource('dynamodb', region_name=region)
        table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])
        
        if investigation_window_hours is None:
            investigation_window_hours = float(os.environ.get('INVESTIGATION_WINDOW_HOURS', '1'))
        
        response = table.get_item(Key={'alarm_name': alarm_name})
        
        if 'Item' in response:
            last_investigation = float(response['Item']['timestamp'])
            time_since_investigation = time.time() - last_investigation
            
            if time_since_investigation < (investigation_window_hours * 3600):
                logger.info(f"Alarm {alarm_name} already investigated {time_since_investigation:.0f} seconds ago")
                return False, time_since_investigation
        
        ttl_seconds = int(investigation_window_hours * 3600)
        table.put_item(Item={
            'alarm_name': alarm_name,
            'timestamp': Decimal(str(time.time())),
            'ttl': int(time.time() + ttl_seconds)
        })
        
        logger.info(f"Recording new investigation for alarm {alarm_name} with TTL of {ttl_seconds} seconds")
        return True, 0
        
    except Exception as e:
        logger.error(f"DynamoDB error: {str(e)}")
        return True, 0

def handler(event, context):
    logger.info(f"Received alarm event: {json.dumps(event)}")
    if 'source' in event and event['source'] == 'aws.cloudwatch':
        alarm_data = event.get('detail', event)
    else:
        alarm_data = event
    if 'alarmData' in alarm_data:
        alarm_state = alarm_data.get('alarmData', {}).get('state', {}).get('value')
        alarm_name = alarm_data.get('alarmData', {}).get('alarmName', 'Unknown Alarm')
    elif 'state' in alarm_data:
        alarm_state = alarm_data.get('state', {}).get('value')
        alarm_name = alarm_data.get('alarmName', 'Unknown Alarm')
    else:
        alarm_state = 'ALARM'
        alarm_name = 'Manual Test Alarm'
    if alarm_state != 'ALARM':
        logger.info(f"Skipping non-ALARM state: {alarm_state}")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Skipped non-alarm state: {alarm_state}',
                'alarm': alarm_name
            })
        }
    
    should_process, time_since = should_investigate(alarm_name)
    if not should_process:
        logger.info(f"Skipping duplicate investigation for {alarm_name} (investigated {time_since:.0f}s ago)")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Already investigated {time_since:.0f} seconds ago',
                'alarm': alarm_name,
                'duplicate': True
            })
        }
    
    try:
        bedrock = BedrockAgentClient(
            model_id=os.environ['BEDROCK_MODEL_ID'],
            tool_lambda_arn=os.environ['TOOL_LAMBDA_ARN'],
            max_tokens=int(os.environ['MAX_TOKENS'])
        )
        prompt = PromptTemplate.generate_investigation_prompt(
            alarm_event=event,
            investigation_depth=os.environ['INVESTIGATION_DEPTH']
        )
        
        logger.info("Invoking Claude for investigation...")
        try:
            analysis = bedrock.investigate_with_tools(prompt)
            logger.info("Investigation complete, sending notification...")
        except Exception as bedrock_error:
            logger.error(f"Bedrock investigation failed: {str(bedrock_error)}")
            analysis = f"""
Investigation Error - Bedrock Unavailable
========================================

An error occurred while invoking Claude for investigation:
{str(bedrock_error)}

Manual Investigation Required:
1. Check the alarm details in the CloudWatch console
2. Review the affected resource logs
3. Examine recent changes or deployments
4. Verify IAM permissions and resource configurations

Alarm Details:
- Name: {alarm_name}
- State: {alarm_state}
- Region: {event.get('region', 'unknown')}

This is an automated fallback message when Claude investigation fails.
"""
        region = os.environ.get('BEDROCK_REGION', 'us-east-1')
        sns = boto3.client('sns', region_name=region)
        
        message = format_notification(alarm_name, alarm_state, analysis, event)
        
        sns.publish(
            TopicArn=os.environ['SNS_TOPIC_ARN'],
            Subject=f"🔍 CloudWatch Alarm Investigation: {alarm_name}",
            Message=message
        )
        
        logger.info("Notification sent successfully")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'alarm': alarm_name,
                'state': alarm_state,
                'investigation_complete': True,
                'analysis_length': len(analysis)
            })
        }
        
    except Exception as e:
        logger.error(f"Error during investigation: {str(e)}", exc_info=True)
        
        # Send error notification
        try:
            region = os.environ.get('BEDROCK_REGION', 'us-east-1')
            sns = boto3.client('sns', region_name=region)
            sns.publish(
                TopicArn=os.environ['SNS_TOPIC_ARN'],
                Subject=f"❌ Investigation Failed: {alarm_name}",
                Message=f"""
CloudWatch Alarm Investigation Error
====================================

Alarm: {alarm_name}
State: {alarm_state}

Error Details:
{str(e)}

Please check the Lambda logs for more information.
"""
            )
        except Exception as sns_error:
            logger.error(f"Failed to send error notification: {str(sns_error)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'alarm': alarm_name
            })
        }

def format_notification(alarm_name, alarm_state, analysis, event):
    """Format the notification message with Claude's analysis."""
    
    # Extract alarm details for context
    region = event.get('region', os.environ.get('AWS_DEFAULT_REGION', 'unknown'))
    account_id = event.get('accountId', 'unknown')
    
    # Build console URL for the alarm
    console_url = f"https://console.aws.amazon.com/cloudwatch/home?region={region}#alarmsV2:alarm/{alarm_name}"
    
    return f"""
CloudWatch Alarm Investigation Results
======================================

Alarm: {alarm_name}
State: {alarm_state}
Region: {region}
Account: {account_id}

Console Link: {console_url}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Claude's Investigation & Analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{analysis}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This investigation was performed automatically by Claude Opus 4.1 using AWS API calls.
For questions or improvements, please contact your CloudWatch Alarm Triage administrator.
"""