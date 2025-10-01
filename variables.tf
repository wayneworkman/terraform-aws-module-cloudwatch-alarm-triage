variable "sns_topic_arn" {
  description = "ARN of the SNS topic for notifications"
  type        = string
}

variable "bedrock_model_id" {
  description = "Bedrock model identifier with cross-region inference (defaults to Claude Sonnet 4.5 which outperforms Opus 4.1 while being faster and more cost-effective)"
  type        = string
  default     = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
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
  description = "Memory allocation for orchestrator Lambda in MB"
  type        = number
  default     = 512
}

variable "tool_lambda_memory_size" {
  description = "Memory allocation for tool Lambda in MB"
  type        = number
  default     = 512
}

variable "lambda_timeout" {
  description = "Orchestrator Lambda timeout in seconds"
  type        = number
  default     = 900  # 15 minutes - maximum Lambda timeout
}

variable "tool_lambda_timeout" {
  description = "Tool Lambda timeout in seconds"
  type        = number
  default     = 120  # 2 minutes
}

variable "tool_lambda_reserved_concurrency" {
  description = "Reserved concurrent executions for tool Lambda (-1 for no limit)"
  type        = number
  default     = -1
}

variable "investigation_window_hours" {
  description = "Hours to wait before allowing re-investigation of the same alarm"
  type        = number
  default     = 24
  
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

variable "reports_bucket_logging" {
  description = "Optional S3 access logging configuration for the reports bucket"
  type = object({
    target_bucket = string
    target_prefix = string
  })
  default = null
}

variable "reports_bucket_lifecycle_days" {
  description = "Number of days after which to delete objects (both current and non-current versions). If null, no lifecycle policy is created."
  type        = number
  default     = null
  
  validation {
    condition     = var.reports_bucket_lifecycle_days == null || var.reports_bucket_lifecycle_days > 0
    error_message = "Lifecycle days must be null or a positive number"
  }
}

variable "log_level" {
  description = "Logging level for Lambda functions (ERROR, INFO, DEBUG)"
  type        = string
  default     = "INFO"
  
  validation {
    condition     = contains(["ERROR", "INFO", "DEBUG"], var.log_level)
    error_message = "Log level must be one of: ERROR, INFO, DEBUG"
  }
}