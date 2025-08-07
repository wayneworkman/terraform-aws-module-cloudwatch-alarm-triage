variable "prefix" {
  description = "Prefix for all demo resources to ensure uniqueness"
  type        = string
  default     = "triage-demo"
}

variable "notification_email" {
  description = "Email address for alarm notifications"
  type        = string
}

variable "enable_demo_failures" {
  description = "Enable the failing Lambda to run (set to false to stop demo)"
  type        = bool
  default     = true
}