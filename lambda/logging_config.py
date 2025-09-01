"""
Logging configuration module for CloudWatch Alarm Triage Lambda functions.

Log Levels:
- ERROR: Only errors (default)
- INFO: Errors + key operational messages
- DEBUG: All messages including detailed traces
"""

import logging
import os

def configure_logging():
    """
    Configure logging based on LOG_LEVEL environment variable.
    
    LOG_LEVEL values:
    - ERROR: Only log errors
    - INFO: Log errors and important information (default)
    - DEBUG: Log everything including detailed traces
    """
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    
    # Map string levels to logging constants
    level_map = {
        'ERROR': logging.ERROR,
        'INFO': logging.INFO,
        'DEBUG': logging.DEBUG
    }
    
    # Default to INFO if invalid level provided
    numeric_level = level_map.get(log_level, logging.INFO)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(numeric_level)
    
    # Ensure we have a handler (Lambda provides one by default)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

def get_logger(name=None):
    """Get a logger instance with the configured level."""
    return logging.getLogger(name) if name else logging.getLogger()