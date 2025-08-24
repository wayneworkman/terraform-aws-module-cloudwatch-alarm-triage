import json
import os
import boto3
import logging
import time
from datetime import datetime
from decimal import Decimal
from bedrock_client import BedrockAgentClient
from prompt_template import PromptTemplate

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def save_report_to_s3(alarm_name, alarm_state, analysis, event):
    """Save investigation report to S3 bucket."""
    try:
        bucket_name = os.environ.get('REPORTS_BUCKET')
        if not bucket_name:
            logger.warning("REPORTS_BUCKET not configured, skipping S3 save")
            return None
            
        region = os.environ.get('BEDROCK_REGION', 'us-east-1')
        s3 = boto3.client('s3', region_name=region)
        
        # Generate report filename with timestamp
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        # Clean alarm name for filename (replace non-alphanumeric chars)
        clean_alarm_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in alarm_name)
        report_key = f"reports/{datetime.utcnow().strftime('%Y/%m/%d')}/{clean_alarm_name}-{timestamp}.json"
        
        # Create comprehensive report
        report = {
            'alarm_name': alarm_name,
            'alarm_state': alarm_state,
            'investigation_timestamp': datetime.utcnow().isoformat(),
            'event': event,
            'analysis': analysis,
            'metadata': {
                'bedrock_model': os.environ.get('BEDROCK_MODEL_ID'),
                'region': region,
                'account_id': event.get('accountId', 'unknown')
            }
        }
        
        # Upload to S3
        s3.put_object(
            Bucket=bucket_name,
            Key=report_key,
            Body=json.dumps(report, indent=2),
            ContentType='application/json',
            ServerSideEncryption='AES256'
        )
        
        logger.info(f"Report saved to S3: s3://{bucket_name}/{report_key}")
        return f"s3://{bucket_name}/{report_key}"
        
    except Exception as e:
        logger.error(f"Failed to save report to S3: {str(e)}")
        return None

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
            tool_lambda_arn=os.environ['TOOL_LAMBDA_ARN']
        )
        prompt = PromptTemplate.generate_investigation_prompt(
            alarm_event=event
        )
        
        logger.info("Invoking AI model for investigation...")
        try:
            analysis = bedrock.investigate_with_tools(prompt)
            logger.info("Investigation complete, sending notification...")
        except Exception as bedrock_error:
            logger.error(f"Bedrock investigation failed: {str(bedrock_error)}")
            analysis = f"""
Investigation Error - Bedrock Unavailable
========================================

An error occurred while invoking AI model for investigation:
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

This is an automated fallback message when AI investigation fails.
"""
        
        # Save report to S3
        s3_location = save_report_to_s3(alarm_name, alarm_state, analysis, event)
        
        region = os.environ.get('BEDROCK_REGION', 'us-east-1')
        sns = boto3.client('sns', region_name=region)
        
        message = format_notification(alarm_name, alarm_state, analysis, event, s3_location)
        
        sns.publish(
            TopicArn=os.environ['SNS_TOPIC_ARN'],
            Subject=f"🔍 CloudWatch Alarm Investigation: {alarm_name}",
            Message=message
        )
        
        logger.info("Notification sent successfully")
        
        response_body = {
            'alarm': alarm_name,
            'state': alarm_state,
            'investigation_complete': True,
            'analysis_length': len(analysis)
        }
        
        if s3_location:
            response_body['report_location'] = s3_location
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body)
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

def format_notification(alarm_name, alarm_state, analysis, event, s3_location=None):
    """Format the notification message with AI model's analysis."""
    
    # Extract alarm details for context
    region = event.get('region', os.environ.get('AWS_DEFAULT_REGION', 'unknown'))
    account_id = event.get('accountId', 'unknown')
    
    # Build console URL for the alarm
    console_url = f"https://console.aws.amazon.com/cloudwatch/home?region={region}#alarmsV2:alarm/{alarm_name}"
    
    # Add S3 report location if available
    report_section = ""
    if s3_location:
        report_section = f"""
Full Report Location:
{s3_location}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    return f"""
CloudWatch Alarm Investigation Results
======================================

Alarm: {alarm_name}
State: {alarm_state}
Region: {region}
Account: {account_id}

Console Link: {console_url}
{report_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AI Investigation & Analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{analysis}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This investigation was performed automatically by AWS Bedrock using AWS API calls.
For questions or improvements, please contact your CloudWatch Alarm Triage administrator.
"""