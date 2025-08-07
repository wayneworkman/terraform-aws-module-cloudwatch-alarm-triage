import boto3
import json
import logging
import os
import time

logger = logging.getLogger()

class BedrockAgentClient:
    def __init__(self, model_id, tool_lambda_arn, max_tokens):
        region = os.environ.get('BEDROCK_REGION')
        if not region:
            region = os.environ.get('AWS_REGION', 'us-east-2')
        logger.info(f"Initializing Bedrock client in region: {region}")
        from botocore.config import Config
        config = Config(
            read_timeout=300,  # 5 minutes read timeout to handle long Claude responses
            connect_timeout=10,
            retries={'max_attempts': 0}
        )
        self.bedrock = boto3.client(
            'bedrock-runtime', 
            region_name=region,
            config=config,
            endpoint_url=f'https://bedrock-runtime.{region}.amazonaws.com'
        )
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.model_id = model_id
        self.tool_lambda_arn = tool_lambda_arn
        self.max_tokens = max_tokens
        
    def investigate_with_tools(self, prompt):
        try:
            tool_calls = []
            
            def execute_tool(tool_input):
                try:
                    logger.info(f"Executing tool with input: {json.dumps(tool_input)}")
                    response = self.lambda_client.invoke(
                        FunctionName=self.tool_lambda_arn,
                        InvocationType='RequestResponse',
                        Payload=json.dumps(tool_input)
                    )
                    result = json.loads(response['Payload'].read())
                    
                    if response['StatusCode'] == 200:
                        body = json.loads(result.get('body', '{}'))
                        tool_calls.append({
                            'input': tool_input,
                            'output': body.get('output', 'No output')[:500]
                        })
                        return body
                    else:
                        error_msg = f"Tool execution failed with status {response['StatusCode']}"
                        logger.error(error_msg)
                        return {'success': False, 'output': error_msg}
                        
                except Exception as e:
                    error_msg = f"Tool execution error: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    return {'success': False, 'output': error_msg}
            messages = [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            tools = [
                {
                    "name": "aws_investigator",
                    "description": "Execute AWS CLI commands or Python/boto3 scripts to investigate AWS resources. The tool runs in an environment with AWS CLI v2 and Python 3.13 with boto3 pre-installed.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["cli", "python"],
                                "description": "Type of command to execute: 'cli' for AWS CLI commands, 'python' for Python/boto3 scripts"
                            },
                            "command": {
                                "type": "string",
                                "description": "AWS CLI command (e.g., 'aws ec2 describe-instances') or Python code to execute. For Python, set a 'result' variable with the output."
                            }
                        },
                        "required": ["type", "command"]
                    }
                }
            ]
            logger.info("Invoking Claude with tool support...")
            max_iterations = 100  # Increased from 50 to ensure complete analysis
            final_response = ""
            retry_count = 0
            max_retries = 3
            
            for iteration in range(max_iterations):
                try:
                    response = self.bedrock.invoke_model(
                        modelId=self.model_id,
                        body=json.dumps({
                            "anthropic_version": "bedrock-2023-05-31",
                            "messages": messages,
                            "max_tokens": self.max_tokens,
                            "temperature": 0.3,
                            "tools": tools,
                            "tool_choice": {"type": "auto"}
                        })
                    )
                    retry_count = 0
                    
                except Exception as e:
                    error_str = str(e)
                    error_type = type(e).__name__
                    if ('ThrottlingException' in error_str or 
                        'ServiceQuotaExceededException' in error_str or
                        'Read timeout on endpoint' in error_str or
                        'ReadTimeoutError' in error_str or
                        error_type == 'ReadTimeoutError'):
                        retry_count += 1
                        if retry_count <= max_retries:
                            if 'timeout' in error_str.lower() or error_type == 'ReadTimeoutError':
                                wait_time = min(5 * retry_count, 20)
                                logger.warning(f"Bedrock read timeout ({error_type}), retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                            else:
                                wait_time = min(2 ** retry_count, 30)
                                logger.warning(f"Bedrock throttled, retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Max retries exceeded for Bedrock: {error_str}")
                            raise
                    else:
                        logger.error(f"Non-retryable Bedrock error ({error_type}): {error_str}")
                        raise
                result = json.loads(response['body'].read())
                assistant_message = result.get('content', [])
                messages.append({
                    "role": "assistant",
                    "content": assistant_message
                })
                # First pass: check if there are any tool uses
                tool_use_found = False
                tool_results = []
                
                for content_block in assistant_message:
                    if content_block.get('type') == 'tool_use':
                        tool_use_found = True
                        break
                
                # Second pass: process the content blocks
                for content_block in assistant_message:
                    if content_block.get('type') == 'tool_use':
                        tool_id = content_block.get('id')
                        tool_name = content_block.get('name')
                        tool_input = content_block.get('input', {})
                        
                        logger.info(f"Claude requesting tool: {tool_name}")
                        if tool_name == 'aws_investigator':
                            tool_result = execute_tool(tool_input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": json.dumps(tool_result)
                            })
                        else:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": json.dumps({
                                    "success": False,
                                    "output": f"Unknown tool: {tool_name}"
                                })
                            })
                    elif content_block.get('type') == 'text':
                        text_content = content_block.get('text', '')
                        if text_content:
                            # Only capture text as final response when no tools are being used
                            if not tool_use_found:
                                final_response = text_content
                                logger.info(f"Claude final response received (length: {len(text_content)} chars)")
                            else:
                                logger.info(f"Claude intermediate text (length: {len(text_content)} chars)")
                if tool_use_found and tool_results:
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
                    time.sleep(0.5)
                else:
                    break
            logger.info(f"Investigation complete. Tool calls made: {len(tool_calls)}")
            for i, call in enumerate(tool_calls[:5], 1):
                logger.info(f"Tool call {i}: {call['input']['type']} - {call['input'].get('command', '')[:100]}")
            
            return final_response if final_response else "Investigation completed but no analysis was generated."
            
        except Exception as e:
            error_msg = f"Bedrock invocation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return f"""
Investigation Error
==================

An error occurred while invoking Claude for investigation:
{str(e)}

Please check the Lambda logs for more details.

Troubleshooting Steps:
1. Verify Bedrock model access in your region
2. Check IAM permissions for Bedrock invocation
3. Ensure the tool Lambda is properly configured
4. Verify Claude Opus 4.1 is available in your region
"""