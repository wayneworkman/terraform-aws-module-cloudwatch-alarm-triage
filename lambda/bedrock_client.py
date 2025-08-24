import boto3
import json
import logging
import os
import time
import re

logger = logging.getLogger()

class BedrockAgentClient:
    def __init__(self, model_id, tool_lambda_arn):
        region = os.environ.get('BEDROCK_REGION')
        if not region:
            region = os.environ.get('AWS_REGION', 'us-east-2')
        logger.info(f"Initializing Bedrock client in region: {region}")
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
            
            def execute_tool(command):
                try:
                    logger.info(f"Executing Python tool with command: {command[:200]}...")
                    
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
            tool_prompt = f"""You are an AI assistant investigating AWS CloudWatch alarms with the ability to execute Python code.

TOOL USAGE INSTRUCTIONS:
When you need to execute Python code to investigate AWS resources, you MUST follow this exact format:

1. First line must contain ONLY: TOOL: python_executor
2. Immediately follow with a markdown code fence containing your Python code
3. Do not include any text between the tool declaration and the code fence

Example of correct format:
TOOL: python_executor
```python
# Your investigation code here
ec2 = boto3.client('ec2')
response = ec2.describe_instances()
print(response)
result = {{"instances": response}}
```

IMPORTANT RULES:
- The first line of your response must be "TOOL: python_executor" if you want to execute code
- Use only one code fence per response
- After receiving execution results, you can continue investigation or provide analysis
- If you don't need to execute code, just respond normally without the TOOL: prefix
- Always use print() statements to show investigation progress
- Set 'result' variable with structured data for final output
- All standard modules and boto3 are pre-imported - do NOT use import statements
- You can make multiple tool calls to investigate thoroughly

USER REQUEST:
{prompt}"""
            
            # Initialize conversation with the tool-augmented prompt
            messages = [
                {
                    "role": "user",
                    "content": [{"text": tool_prompt}]
                }
            ]
            
            logger.info("Invoking model with Converse API...")
            max_iterations = 100  # Allow many iterations for thorough investigation
            final_response = ""
            retry_count = 0
            max_retries = 3
            
            for iteration in range(max_iterations):
                try:
                    # Call the Converse API
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
                
                # Extract response text from Converse API response
                response_message = response['output']['message']
                response_text = response_message['content'][0]['text']
                
                # Add assistant's response to conversation history
                messages.append({
                    "role": "assistant",
                    "content": [{"text": response_text}]
                })
                
                # Check if the response contains a tool call
                lines = response_text.strip().split('\n')
                if lines and lines[0].strip().upper().startswith('TOOL: PYTHON_EXECUTOR'):
                    # Extract code using regex
                    code_match = re.search(r'```python\n(.*?)\n```', response_text, re.DOTALL)
                    if code_match:
                        code = code_match.group(1).strip()
                        logger.info(f"Model requesting Python execution (iteration {iteration + 1})")
                        
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
                        
                        # Small delay between tool calls
                        time.sleep(0.5)
                    else:
                        logger.warning("Tool call detected but no code block found")
                        messages.append({
                            "role": "user",
                            "content": [{"text": "Tool call detected but no code block found. Please provide the code in a markdown code fence."}]
                        })
                else:
                    # No tool call, this is the final response
                    final_response = response_text
                    logger.info(f"Model final response received (length: {len(response_text)} chars)")
                    break
            
            logger.info(f"Investigation complete. Tool calls made: {len(tool_calls)}")
            for i, call in enumerate(tool_calls[:5], 1):
                logger.info(f"Tool call {i}: {call['input'].get('command', '')[:100]}")
            
            return final_response if final_response else "Investigation completed but no analysis was generated."
            
        except Exception as e:
            error_msg = f"Bedrock invocation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return f"""
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