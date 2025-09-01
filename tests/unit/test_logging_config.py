import pytest
import logging
from unittest.mock import Mock, patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../lambda')))

from logging_config import configure_logging, get_logger

class TestLoggingConfiguration:
    """Test logging configuration with different log levels."""
    
    def teardown_method(self):
        """Reset logging after each test."""
        # Reset root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)
        root_logger.handlers = []
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'ERROR'})
    def test_configure_logging_error_level(self):
        """Test that ERROR log level only logs errors."""
        logger = configure_logging()
        
        assert logger.level == logging.ERROR
        assert logger.isEnabledFor(logging.ERROR)
        assert not logger.isEnabledFor(logging.INFO)
        assert not logger.isEnabledFor(logging.DEBUG)
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'INFO'})
    def test_configure_logging_info_level(self):
        """Test that INFO log level logs info and errors."""
        logger = configure_logging()
        
        assert logger.level == logging.INFO
        assert logger.isEnabledFor(logging.ERROR)
        assert logger.isEnabledFor(logging.INFO)
        assert not logger.isEnabledFor(logging.DEBUG)
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'})
    def test_configure_logging_debug_level(self):
        """Test that DEBUG log level logs everything."""
        logger = configure_logging()
        
        assert logger.level == logging.DEBUG
        assert logger.isEnabledFor(logging.ERROR)
        assert logger.isEnabledFor(logging.INFO)
        assert logger.isEnabledFor(logging.DEBUG)
    
    @patch.dict(os.environ, {}, clear=True)
    def test_configure_logging_default_level(self):
        """Test that default log level is INFO when not specified."""
        logger = configure_logging()
        
        assert logger.level == logging.INFO
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'INVALID'})
    def test_configure_logging_invalid_level(self):
        """Test that invalid log level defaults to INFO."""
        logger = configure_logging()
        
        assert logger.level == logging.INFO
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'info'})
    def test_configure_logging_case_insensitive(self):
        """Test that log level is case insensitive."""
        logger = configure_logging()
        
        assert logger.level == logging.INFO
    
    def test_get_logger_with_name(self):
        """Test getting a named logger."""
        logger = get_logger('test_module')
        
        assert logger.name == 'test_module'
    
    def test_get_logger_without_name(self):
        """Test getting the root logger."""
        logger = get_logger()
        
        assert logger.name == 'root'
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'ERROR'})
    def test_logging_output_error_level(self, caplog):
        """Test that only errors are logged at ERROR level."""
        logger = configure_logging()
        
        # Set caplog to ERROR level to match logger config
        with caplog.at_level(logging.ERROR):
            logger.debug("Debug message")
            logger.info("Info message")
            logger.error("Error message")
        
        # Only error message should be captured
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == 'ERROR'
        assert "Error message" in caplog.records[0].message
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'INFO'})
    def test_logging_output_info_level(self, caplog):
        """Test that info and errors are logged at INFO level."""
        logger = configure_logging()
        
        # Set caplog to INFO level to match logger config
        with caplog.at_level(logging.INFO):
            logger.debug("Debug message")
            logger.info("Info message")
            logger.error("Error message")
        
        # Info and error messages should be captured
        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == 'INFO'
        assert caplog.records[1].levelname == 'ERROR'
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'})
    def test_logging_output_debug_level(self, caplog):
        """Test that all messages are logged at DEBUG level."""
        logger = configure_logging()
        
        with caplog.at_level(logging.DEBUG):
            logger.debug("Debug message")
            logger.info("Info message")
            logger.error("Error message")
        
        # All messages should be captured
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == 'DEBUG'
        assert caplog.records[1].levelname == 'INFO'
        assert caplog.records[2].levelname == 'ERROR'
    
    def test_handler_configuration(self):
        """Test that handler is configured properly."""
        logger = configure_logging()
        
        # Should have at least one handler
        assert len(logger.handlers) > 0
        
        # Handler should be a StreamHandler for Lambda
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'})
    def test_conditional_debug_logging(self):
        """Test conditional debug logging pattern."""
        logger = configure_logging()
        
        # This pattern is used in bedrock_client.py
        if logger.isEnabledFor(logging.DEBUG):
            # This should execute in DEBUG mode
            assert True
        else:
            # This should not execute
            assert False, "Should not reach here in DEBUG mode"
    
    @patch.dict(os.environ, {'LOG_LEVEL': 'INFO'})
    def test_conditional_debug_logging_info_level(self):
        """Test conditional debug logging doesn't execute at INFO level."""
        logger = configure_logging()
        
        # This pattern is used in bedrock_client.py
        if logger.isEnabledFor(logging.DEBUG):
            # This should not execute in INFO mode
            assert False, "Should not execute debug code in INFO mode"
        else:
            # This should execute
            assert True