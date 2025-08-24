import pytest
import json
from unittest.mock import patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from prompt_template import PromptTemplate

class TestPromptTemplate:
    
    def test_generate_investigation_prompt(self, sample_alarm_event):
        """Test investigation prompt generation."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check basic structure
        assert "CloudWatch Alarm has triggered" in prompt
        assert "comprehensive" in prompt.lower()
        assert "python_executor" in prompt
        
        # Check alarm event is included
        assert "test-lambda-errors" in prompt
        assert "AWS/Lambda" in prompt
        
        # Check output format is specified
        assert "EXECUTIVE SUMMARY" in prompt
        assert "INVESTIGATION DETAILS" in prompt
        assert "IMMEDIATE ACTIONS" in prompt
    
    def test_generate_investigation_prompt_tool_instructions(self, sample_alarm_event):
        """Test that tool usage instructions are included."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check tool instructions
        assert "python_executor" in prompt
        assert "pre-imported" in prompt.lower() or "pre imported" in prompt.lower()
        # Check for examples
        assert "boto3.client" in prompt
        assert "boto3" in prompt
        assert "result" in prompt
    
    def test_generate_investigation_prompt_investigation_steps(self, sample_alarm_event):
        """Test that investigation steps are properly outlined."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check systematic investigation steps
        assert "Initial Assessment" in prompt
        assert "Data Gathering" in prompt
        assert "Root Cause Analysis" in prompt
        assert "Impact Assessment" in prompt
        assert "Historical Context" in prompt
        assert "Remediation Steps" in prompt
        
        # Check specific investigation activities
        assert "CloudWatch Logs" in prompt
        assert "CloudWatch metrics" in prompt
        assert "IAM roles and policies" in prompt
        assert "CloudTrail events" in prompt
        assert "AWS Health Dashboard" in prompt
    
    def test_generate_investigation_prompt_security_context(self, sample_alarm_event):
        """Test that security context is included."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check security limitations
        assert "No S3 object content access" in prompt
        assert "No DynamoDB data reads" in prompt
        assert "No Secrets Manager access" in prompt
        assert "No Parameter Store SecureString access" in prompt
        
        # Check read-only emphasis
        assert "read-only access" in prompt
    
    def test_generate_investigation_prompt_time_context(self, sample_alarm_event):
        """Test that time context is included."""
        with patch('prompt_template.datetime') as mock_datetime:
            mock_datetime.now.return_value.isoformat.return_value = '2025-08-06T12:00:00+00:00'
            
            prompt = PromptTemplate.generate_investigation_prompt(
                sample_alarm_event
            )
            
            assert "Current Time" in prompt
            assert "2025-08-06T12:00:00+00:00" in prompt
    
    def test_generate_investigation_prompt_json_formatting(self, sample_alarm_event):
        """Test that alarm event is properly JSON formatted."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check that JSON is properly formatted
        assert "```json" in prompt
        assert "```" in prompt
        
        # Extract JSON section and verify it's valid
        json_start = prompt.find("```json") + 7
        json_end = prompt.find("```", json_start)
        json_content = prompt[json_start:json_end].strip()
        
        # Should be valid JSON
        try:
            parsed = json.loads(json_content)
            assert parsed['alarmData']['alarmName'] == 'test-lambda-errors'
        except json.JSONDecodeError:
            pytest.fail("Generated JSON is not valid")
    
    def test_generate_investigation_prompt_output_format(self, sample_alarm_event):
        """Test that the required output format is specified."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check all required sections
        required_sections = [
            "🚨 EXECUTIVE SUMMARY",
            "🔍 INVESTIGATION DETAILS",
            "📊 ROOT CAUSE ANALYSIS", 
            "💥 IMPACT ASSESSMENT",
            "🔧 IMMEDIATE ACTIONS",
            "🛡️ PREVENTION MEASURES",
            "📈 MONITORING RECOMMENDATIONS",
            "📝 ADDITIONAL NOTES"
        ]
        
        for section in required_sections:
            assert section in prompt
    
    def test_generate_investigation_prompt_specific_guidance(self, sample_alarm_event):
        """Test that specific guidance and best practices are included."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        # Check specific guidance
        assert "python_executor tool extensively" in prompt
        assert "Don't make assumptions" in prompt
        assert "Be specific" in prompt
        assert "Be actionable" in prompt
        assert "Consider the context" in prompt
        assert "Check multiple sources" in prompt
        assert "Time-box commands" in prompt
        assert "Handle errors gracefully" in prompt
        
        # Check time ranges
        assert "last 30 mins for logs" in prompt
        assert "2 hours for metrics" in prompt
    
    def test_generate_investigation_prompt_production_context(self, sample_alarm_event):
        """Test that production incident context is emphasized."""
        prompt = PromptTemplate.generate_investigation_prompt(
            sample_alarm_event
        )
        
        assert "production incident" in prompt
        assert "Be thorough but efficient" in prompt
        assert "gathering facts" in prompt
        assert "not speculation" in prompt
    
    def test_generate_investigation_prompt_different_alarm_types(self):
        """Test prompt generation with different alarm types."""
        # Lambda alarm
        lambda_event = {
            "alarmData": {
                "alarmName": "lambda-memory-alarm",
                "configuration": {
                    "metrics": [{
                        "metricStat": {
                            "metric": {
                                "namespace": "AWS/Lambda",
                                "name": "MemoryUtilization"
                            }
                        }
                    }]
                }
            }
        }
        
        # EC2 alarm
        ec2_event = {
            "alarmData": {
                "alarmName": "ec2-cpu-alarm", 
                "configuration": {
                    "metrics": [{
                        "metricStat": {
                            "metric": {
                                "namespace": "AWS/EC2",
                                "name": "CPUUtilization"
                            }
                        }
                    }]
                }
            }
        }
        
        # Both should generate valid prompts
        lambda_prompt = PromptTemplate.generate_investigation_prompt(lambda_event)
        ec2_prompt = PromptTemplate.generate_investigation_prompt(ec2_event)
        
        assert "lambda-memory-alarm" in lambda_prompt
        assert "AWS/Lambda" in lambda_prompt
        assert "ec2-cpu-alarm" in ec2_prompt
        assert "AWS/EC2" in ec2_prompt
        
        # Both should have same structure
        for prompt in [lambda_prompt, ec2_prompt]:
            assert "EXECUTIVE SUMMARY" in prompt
            assert "python_executor" in prompt