import boto3
import json
import os
import time
import re
import logging
from logging_config import get_logger

logger = get_logger(__name__)

class BedrockAgentClient:
    def __init__(self, model_id, tool_lambda_arn):
        region = os.environ.get('BEDROCK_REGION')
        if not region:
            region = os.environ.get('AWS_REGION', 'us-east-2')
        logger.debug(f"Initializing Bedrock client in region: {region}")
        from botocore.config import Config
        config = Config(
            read_timeout=300,  # 5 minutes read timeout to handle long model responses
            connect_timeout=10,
            retries={'max_attempts': 0}
        )
        self.bedrock = boto3.client(
            'bedrock-runtime', 
            region_name=region,
            config=config
        )
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.model_id = model_id
        self.tool_lambda_arn = tool_lambda_arn
        
    def investigate_with_tools(self, prompt):
        try:
            tool_calls = []
            full_context = []  # Track complete conversation
            iteration_count = 0  # Track number of Bedrock invocations
            
            def execute_tool(command):
                try:
                    logger.debug(f"Executing Python tool with command: {command[:200]}...")
                    
                    response = self.lambda_client.invoke(
                        FunctionName=self.tool_lambda_arn,
                        InvocationType='RequestResponse',
                        Payload=json.dumps({'command': command})
                    )
                    result = json.loads(response['Payload'].read())
                    
                    if response['StatusCode'] == 200:
                        body = json.loads(result.get('body', '{}'))
                        tool_calls.append({
                            'input': {'command': command[:200]},
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
            
            # Create the initial prompt with tool instructions
            tool_prompt = f"""You have access to a Python execution tool for investigating AWS resources.

## CRITICAL TOOL USAGE RULES

To execute Python code, your response MUST follow this EXACT format:

1. **First line must be**: TOOL: python_executor
2. **Next line must start the code block**: ```python
3. **Then your code**
4. **End with**: ```
5. **Nothing else in that response**

CORRECT example:
TOOL: python_executor
```python
logs = boto3.client('logs', region_name='us-east-2')
response = logs.describe_log_streams(
    logGroupName='/aws/lambda/my-function',
    orderBy='LastEventTime',
    descending=True,
    limit=5
)
print(f"Found {{len(response['logStreams'])}} log streams")
result = response
```

## AVAILABLE MODULES (pre-imported, DO NOT import)
boto3, json, datetime, time, collections, re, os, sys, math, statistics, 
random, itertools, functools, copy, hashlib, urllib, uuid, base64, gzip, zlib

IMPORTANT: 'datetime' is the full module. Use: datetime.datetime(2025, 1, 1) or datetime.timedelta(days=1)
Variables do NOT persist between tool calls. Each execution is independent.

## INVESTIGATION WORKFLOW

1. **Start investigating immediately** - Use tools to gather real data
2. **Continue until you have enough data** - Multiple tool calls are expected
3. **Then provide your final analysis** - Starting with ### means NO MORE TOOLS

## CRITICAL RULES
- You MUST investigate FIRST using tools, THEN provide analysis
- Do NOT skip investigation and provide a report
- Do NOT append tool calls after starting your final report
- When you start your response with ###, that is your FINAL response - no tools after that

## TOOL EXECUTION NOTES
- Use print() liberally to show investigation progress
- Set 'result' variable with key data to return
- Each tool response can only execute one code block
- After each tool result, decide: investigate more OR provide final analysis

## YOUR TASK
{prompt}

Remember: Investigate thoroughly with tools FIRST, then provide your analysis. Do not provide analysis without investigation."""
            
            # Initialize conversation with the tool-augmented prompt
            messages = [
                {
                    "role": "user",
                    "content": [{"text": tool_prompt}]
                }
            ]
            
            # Add initial prompt to full context
            full_context.append({
                "role": "user",
                "content": tool_prompt,
                "timestamp": time.time()
            })
            
            logger.debug("Starting model investigation with Converse API")
            max_iterations = 100  # Allow many iterations for thorough investigation
            final_response = ""
            retry_count = 0
            max_retries = 3
            
            # Track if Nova model has done any investigation
            is_nova = 'nova' in self.model_id.lower()
            
            for iteration in range(max_iterations):
                try:
                    # Call the Converse API
                    iteration_count += 1  # Increment for each Bedrock invocation
                    response = self.bedrock.converse(
                        modelId=self.model_id,
                        messages=messages,
                        inferenceConfig={
                            "temperature": 0.3
                        }
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
                                logger.info(f"Bedrock timeout, retrying (attempt {retry_count}/{max_retries})")
                            else:
                                wait_time = min(2 ** retry_count, 30)
                                logger.info(f"Bedrock throttled, retrying (attempt {retry_count}/{max_retries})")
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Max retries exceeded for Bedrock: {error_str}")
                            raise
                    else:
                        logger.error(f"Non-retryable Bedrock error ({error_type}): {error_str}")
                        raise
                
                # Extract response text from Converse API response
                response_message = response['output']['message']
                response_text = response_message['content'][0]['text']
                
                # Add assistant's response to conversation history
                messages.append({
                    "role": "assistant",
                    "content": [{"text": response_text}]
                })
                
                # Add to full context
                full_context.append({
                    "role": "assistant",
                    "content": response_text,
                    "timestamp": time.time(),
                    "iteration": iteration + 1
                })
                
                # Check if the response contains a tool call
                lines = response_text.strip().split('\n')
                if lines and lines[0].strip().upper().startswith('TOOL: PYTHON_EXECUTOR'):
                    # Extract code using regex
                    code_match = re.search(r'```python\n(.*?)\n```', response_text, re.DOTALL)
                    if code_match:
                        code = code_match.group(1).strip()
                        logger.debug(f"Model requesting Python execution (iteration {iteration + 1})")
                        
                        # Execute the tool
                        tool_result = execute_tool(code)
                        
                        # Add tool result to conversation
                        tool_response = f"""Tool execution result:
Success: {tool_result.get('success', False)}
Output:
{tool_result.get('output', 'No output')}"""
                        
                        messages.append({
                            "role": "user",
                            "content": [{"text": tool_response}]
                        })
                        
                        # Add tool execution to full context
                        full_context.append({
                            "role": "tool_execution",
                            "input": code,
                            "output": tool_result,
                            "timestamp": time.time()
                        })
                        
                        # Small delay between tool calls
                        time.sleep(0.5)
                    else:
                        logger.debug("Tool call detected but no code block found")
                        messages.append({
                            "role": "user",
                            "content": [{"text": "Tool call detected but no code block found. Please provide the code in a markdown code fence."}]
                        })
                else:
                    # No tool call at the beginning, this might be the final response
                    # Check if Nova is trying to skip investigation
                    if is_nova and len(tool_calls) == 0 and iteration == 0:
                        # Model trying to provide analysis without investigation
                        logger.debug("Model attempting to skip investigation. Forcing tool usage.")
                        messages.append({
                            "role": "assistant",
                            "content": [{"text": response_text}]
                        })
                        messages.append({
                            "role": "user",
                            "content": [{"text": "You must investigate first using the Python tool. Start your response with 'TOOL: python_executor' and gather real data from AWS. Do not provide analysis without investigation."}]
                        })
                        continue
                    
                    # This is the final response
                    # But we need to clean up any trailing tool calls that Nova might append
                    final_response = response_text
                    
                    # Check if there's a trailing tool call and remove it
                    # Look for "TOOL: python_executor" anywhere in the response
                    tool_pattern = r'\n*TOOL:\s*python_executor\s*\n```python.*?```.*$'
                    cleaned_response = re.sub(tool_pattern, '', final_response, flags=re.DOTALL | re.IGNORECASE)
                    
                    if cleaned_response != final_response:
                        logger.debug(f"Removed trailing tool call from model response (original: {len(final_response)} chars, cleaned: {len(cleaned_response)} chars)")
                        final_response = cleaned_response.strip()
                    
                    logger.debug(f"Model final response received (length: {len(final_response)} chars)")
                    break
            
            logger.info(f"Investigation complete. Iterations: {iteration_count}, Tool calls: {len(tool_calls)}")
            if logger.isEnabledFor(logging.DEBUG):
                for i, call in enumerate(tool_calls[:5], 1):
                    logger.debug(f"Tool call {i}: {call['input'].get('command', '')[:100]}")
            
            # Return a dictionary with all the information
            return {
                'report': final_response if final_response else "Investigation completed but no analysis was generated.",
                'full_context': full_context,
                'iteration_count': iteration_count,
                'tool_calls': tool_calls
            }
            
        except Exception as e:
            error_msg = f"Bedrock invocation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            error_report = f"""
Investigation Error
==================

An error occurred while invoking model for investigation:
{str(e)}

Please check the Lambda logs for more details.

Troubleshooting Steps:
1. Verify Bedrock model access in your region
2. Check IAM permissions for Bedrock invocation
3. Ensure the tool Lambda is properly configured
4. Verify the configured Bedrock model is available in your region
"""
            # Return dict format for consistency
            return {
                'report': error_report,
                'full_context': [],
                'iteration_count': iteration_count if 'iteration_count' in locals() else 0,
                'tool_calls': tool_calls if 'tool_calls' in locals() else []
            }