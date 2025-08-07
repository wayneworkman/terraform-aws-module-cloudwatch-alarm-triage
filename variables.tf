variable "sns_topic_arn" {
  description = "ARN of the SNS topic for notifications"
  type        = string
}

variable "bedrock_model_id" {
  description = "Bedrock Claude Opus 4.1 model identifier"
  type        = string
  default     = "anthropic.claude-opus-4-1-20250805-v1:0"
}

variable "resource_prefix" {
  description = "Prefix for all created resources to ensure uniqueness"
  type        = string
  default     = ""
}

variable "resource_suffix" {
  description = "Suffix for all created resources to ensure uniqueness"
  type        = string
  default     = ""
}

variable "lambda_memory_size" {
  description = "Memory allocation for orchestrator Lambda"
  type        = number
  default     = 1024
}

variable "tool_lambda_memory_size" {
  description = "Memory allocation for tool Lambda"
  type        = number
  default     = 2048
}

variable "lambda_timeout" {
  description = "Orchestrator Lambda timeout in seconds"
  type        = number
  default     = 900  # 15 minutes - maximum Lambda timeout
}

variable "tool_lambda_timeout" {
  description = "Tool Lambda timeout in seconds"
  type        = number
  default     = 60
}

variable "tool_lambda_reserved_concurrency" {
  description = "Reserved concurrent executions for tool Lambda (-1 for no limit)"
  type        = number
  default     = -1
}

variable "investigation_depth" {
  description = "Depth of investigation (basic, detailed, comprehensive)"
  type        = string
  default     = "comprehensive"
  
  validation {
    condition     = contains(["basic", "detailed", "comprehensive"], var.investigation_depth)
    error_message = "Investigation depth must be one of: basic, detailed, comprehensive"
  }
}

variable "enable_cost_controls" {
  description = "Enable cost control features"
  type        = bool
  default     = true
}

variable "max_tokens_per_investigation" {
  description = "Maximum tokens for Claude response"
  type        = number
  default     = 100000  # Maximum for Claude Opus 4.1 to ensure complete analysis
}

variable "investigation_window_hours" {
  description = "Hours to wait before allowing re-investigation of the same alarm"
  type        = number
  default     = 1
  
  validation {
    condition     = var.investigation_window_hours > 0 && var.investigation_window_hours <= 24
    error_message = "Investigation window must be between 1 and 24 hours"
  }
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}