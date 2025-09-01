import json
import os
import boto3
import time
from datetime import datetime
from decimal import Decimal
from bedrock_client import BedrockAgentClient
from prompt_template import PromptTemplate
from logging_config import configure_logging

# Configure logging based on environment variable
logger = configure_logging()

def save_enhanced_reports_to_s3(alarm_name, alarm_state, investigation_result, event):
    """Save both full context and report-only files to S3 bucket."""
    try:
        bucket_name = os.environ.get('REPORTS_BUCKET')
        if not bucket_name:
            logger.warning("REPORTS_BUCKET not configured, skipping S3 save")
            return None, None, None
            
        region = os.environ.get('BEDROCK_REGION', 'us-east-1')
        s3 = boto3.client('s3', region_name=region)
        
        # Generate S3-friendly timestamp (no colons)
        utc_now = datetime.utcnow()
        timestamp = utc_now.strftime('%Y%m%d_%H%M%S_UTC')
        date_path = utc_now.strftime('%Y/%m/%d')
        
        # Clean alarm name for filename (replace non-alphanumeric chars)
        clean_alarm_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in alarm_name)
        
        # Extract data from investigation result
        if isinstance(investigation_result, dict):
            report = investigation_result.get('report', 'No report available')
            full_context = investigation_result.get('full_context', [])
            iteration_count = investigation_result.get('iteration_count', 0)
            tool_calls = investigation_result.get('tool_calls', [])
        else:
            # Backward compatibility for old format
            report = investigation_result
            full_context = []
            iteration_count = 0
            tool_calls = []
        
        # Save report-only text file (report already has metadata header)
        report_key = f"reports/{date_path}/{timestamp}_{clean_alarm_name}_report.txt"
        s3.put_object(
            Bucket=bucket_name,
            Key=report_key,
            Body=report,
            ContentType='text/plain',
            ServerSideEncryption='AES256'
        )
        logger.debug(f"Report saved to S3: s3://{bucket_name}/{report_key}")
        
        # Build full context text
        model_id = os.environ.get('BEDROCK_MODEL_ID', 'unknown')
        context_text = f"CloudWatch Alarm Investigation Full Context\n"
        context_text += f"{'=' * 60}\n"
        context_text += f"Alarm Name: {alarm_name}\n"
        context_text += f"Alarm State: {alarm_state}\n"
        context_text += f"Investigation Timestamp: {utc_now.isoformat()}\n"
        context_text += f"Bedrock Model: {model_id}\n"
        context_text += f"Total Iterations: {iteration_count}\n"
        context_text += f"Total Tool Calls: {len(tool_calls)}\n"
        context_text += f"{'=' * 60}\n\n"
        
        # Add full conversation context
        for i, entry in enumerate(full_context):
            context_text += f"\n--- Entry {i+1} ---\n"
            context_text += f"Role: {entry.get('role', 'unknown')}\n"
            context_text += f"Timestamp: {datetime.utcfromtimestamp(entry.get('timestamp', 0)).isoformat()}\n"
            
            if entry.get('role') == 'tool_execution':
                context_text += f"Tool Input:\n{entry.get('input', 'N/A')}\n"
                context_text += f"Tool Output:\n{json.dumps(entry.get('output', {}), indent=2)}\n"
            else:
                context_text += f"Content:\n{entry.get('content', 'N/A')}\n"
            
            context_text += "\n"
        
        context_text += f"\n{'=' * 60}\n"
        context_text += f"FINAL REPORT:\n"
        context_text += f"{'=' * 60}\n"
        context_text += report
        
        # Save full context text file
        context_key = f"reports/{date_path}/{timestamp}_{clean_alarm_name}_full_context.txt"
        s3.put_object(
            Bucket=bucket_name,
            Key=context_key,
            Body=context_text,
            ContentType='text/plain',
            ServerSideEncryption='AES256'
        )
        logger.debug(f"Full context saved to S3: s3://{bucket_name}/{context_key}")
        
        # Also save original JSON report for backward compatibility
        json_key = f"reports/{date_path}/{timestamp}_{clean_alarm_name}.json"
        json_report = {
            'alarm_name': alarm_name,
            'alarm_state': alarm_state,
            'investigation_timestamp': utc_now.isoformat(),
            'event': event,
            'analysis': report,
            'iteration_count': iteration_count,
            'tool_calls_count': len(tool_calls),
            'metadata': {
                'bedrock_model': model_id,
                'region': region,
                'account_id': event.get('accountId', 'unknown')
            }
        }
        
        s3.put_object(
            Bucket=bucket_name,
            Key=json_key,
            Body=json.dumps(json_report, indent=2),
            ContentType='application/json',
            ServerSideEncryption='AES256'
        )
        
        return f"s3://{bucket_name}/{report_key}", f"s3://{bucket_name}/{context_key}", f"s3://{bucket_name}/{json_key}"
        
    except Exception as e:
        logger.error(f"Failed to save reports to S3: {str(e)}")
        return None, None, None

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
                logger.debug(f"Alarm {alarm_name} already investigated {time_since_investigation:.0f} seconds ago")
                return False, time_since_investigation
        
        ttl_seconds = int(investigation_window_hours * 3600)
        table.put_item(Item={
            'alarm_name': alarm_name,
            'timestamp': Decimal(str(time.time())),
            'ttl': int(time.time() + ttl_seconds)
        })
        
        logger.debug(f"Recording new investigation for alarm {alarm_name} with TTL of {ttl_seconds} seconds")
        return True, 0
        
    except Exception as e:
        logger.error(f"DynamoDB error: {str(e)}")
        return True, 0

def handler(event, context):
    logger.debug(f"Received alarm event: {json.dumps(event)}")
    
    # Create SNS client once for all notifications
    region = os.environ.get('BEDROCK_REGION', 'us-east-1')
    sns = boto3.client('sns', region_name=region)
    
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
        logger.debug(f"Skipping non-ALARM state: {alarm_state}")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Skipped non-alarm state: {alarm_state}',
                'alarm': alarm_name
            })
        }
    
    should_process, time_since = should_investigate(alarm_name)
    if not should_process:
        logger.info(f"Skipping duplicate investigation for {alarm_name}")
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
        
        logger.info(f"Investigating alarm: {alarm_name}")
        try:
            investigation_result = bedrock.investigate_with_tools(prompt)
            logger.debug("Investigation complete, sending notification...")
            
            # Build the report with metadata header ONCE for both S3 and SNS
            model_id = os.environ.get('BEDROCK_MODEL_ID', 'unknown')
            if isinstance(investigation_result, dict):
                raw_report = investigation_result.get('report', 'No report available')
                iteration_count = investigation_result.get('iteration_count', 0)
                tool_calls = investigation_result.get('tool_calls', [])
                
                # Store the raw report without metadata (metadata goes in the notification header)
                investigation_result['report'] = raw_report
                analysis = raw_report
            else:
                # Backward compatibility
                analysis = investigation_result
                
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
            # Create a result dict for consistency
            investigation_result = {'report': analysis, 'full_context': [], 'iteration_count': 0, 'tool_calls': []}
        
        # Save enhanced reports to S3
        report_location, context_location, json_location = save_enhanced_reports_to_s3(
            alarm_name, alarm_state, investigation_result, event
        )
        
        # Pass investigation details to format_notification
        model_id = os.environ.get('BEDROCK_MODEL_ID', 'unknown')
        iteration_count = investigation_result.get('iteration_count', 0) if isinstance(investigation_result, dict) else 0
        tool_calls_count = len(investigation_result.get('tool_calls', [])) if isinstance(investigation_result, dict) else 0
        message = format_notification(alarm_name, alarm_state, analysis, event, report_location, context_location, model_id, iteration_count, tool_calls_count)
        
        sns.publish(
            TopicArn=os.environ['SNS_TOPIC_ARN'],
            Subject=f"🔍 CloudWatch Alarm Investigation: {alarm_name}",
            Message=message
        )
        
        logger.debug("Notification sent successfully")
        
        response_body = {
            'alarm': alarm_name,
            'state': alarm_state,
            'investigation_complete': True,
            'analysis_length': len(analysis)
        }
        
        if report_location:
            response_body['report_location'] = report_location
        if context_location:
            response_body['context_location'] = context_location
        if json_location:
            response_body['json_location'] = json_location
        
        # Add iteration count if available
        if isinstance(investigation_result, dict):
            response_body['iteration_count'] = investigation_result.get('iteration_count', 0)
            response_body['tool_calls_count'] = len(investigation_result.get('tool_calls', []))
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_body)
        }
        
    except Exception as e:
        logger.error(f"Error during investigation: {str(e)}", exc_info=True)
        
        # Send error notification
        try:
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

def format_notification(alarm_name, alarm_state, analysis, event, report_location=None, context_location=None, model_id=None, iteration_count=0, tool_calls_count=0):
    """Format the notification message with AI model's analysis."""
    
    # Extract alarm details for context
    region = event.get('region', os.environ.get('AWS_DEFAULT_REGION', 'unknown'))
    account_id = event.get('accountId', 'unknown')
    
    # Build console URL for the alarm
    console_url = f"https://console.aws.amazon.com/cloudwatch/home?region={region}#alarmsV2:alarm/{alarm_name}"
    
    # Add S3 report locations if available
    report_section = ""
    if report_location or context_location:
        report_section = "\nInvestigation Files:\n"
        if report_location:
            report_section += f"  • Report: {report_location}\n"
        if context_location:
            report_section += f"  • Full Context: {context_location}\n"
    
    return f"""CloudWatch Alarm Investigation Results
======================================

Alarm: {alarm_name}
State: {alarm_state}
Model: {model_id if model_id else 'Unknown'}
Model Calls: {iteration_count}
Tool Calls: {tool_calls_count}
Region: {region}
Account: {account_id}
Console: {console_url}
{report_section}
--------------------------------------

{analysis}

--------------------------------------
This investigation was performed automatically by AWS Bedrock using AWS API calls.
For questions or improvements, please contact your CloudWatch Alarm Triage administrator.
"""