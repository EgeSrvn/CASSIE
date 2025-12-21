"""
Logging utility for CASSIE backend.

This module provides structured logging with:
- Console output with colors (for development)
- Optional file logging (when configured)
- Integration with configuration loader
- Exception logging with stack traces
- Context support (request ID, user ID, job ID)

Usage:
    from backend.api.utils.logger import get_logger
    
    logger = get_logger(__name__)
    logger.info("Processing job", extra={"job_id": 123})
    logger.error("Job failed", exc_info=True)
"""

import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

# ANSI color codes for console output
class Colors:
    """ANSI color codes for terminal output."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Log level colors
    DEBUG = '\033[36m'      # Cyan
    INFO = '\033[32m'       # Green
    WARNING = '\033[33m'    # Yellow
    ERROR = '\033[31m'      # Red
    CRITICAL = '\033[35m'   # Magenta
    
    # Text colors
    TIMESTAMP = '\033[90m'  # Dark gray
    MODULE = '\033[94m'     # Light blue


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors to console output."""
    
    # Color mapping for log levels
    LEVEL_COLORS = {
        logging.DEBUG: Colors.DEBUG,
        logging.INFO: Colors.INFO,
        logging.WARNING: Colors.WARNING,
        logging.ERROR: Colors.ERROR,
        logging.CRITICAL: Colors.CRITICAL,
    }
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        # Get color for log level
        level_color = self.LEVEL_COLORS.get(record.levelno, Colors.RESET)
        level_name = record.levelname
        
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        
        # Format module name (truncate if too long)
        module = record.name
        if len(module) > 30:
            module = "..." + module[-27:]
        
        # Build context string from extra fields
        context_parts = []
        if hasattr(record, 'request_id'):
            context_parts.append(f"req_id={record.request_id}")
        if hasattr(record, 'user_id'):
            context_parts.append(f"user_id={record.user_id}")
        if hasattr(record, 'job_id'):
            context_parts.append(f"job_id={record.job_id}")
        
        context_str = f" [{', '.join(context_parts)}]" if context_parts else ""
        
        # Format message
        message = record.getMessage()
        
        # Build colored output
        formatted = (
            f"{Colors.TIMESTAMP}[{timestamp}]{Colors.RESET} "
            f"{level_color}[{level_name:8}]{Colors.RESET} "
            f"{Colors.MODULE}[{module}]{Colors.RESET}"
            f"{context_str} "
            f"{message}"
        )
        
        # Add exception info if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        
        return formatted


class FileFormatter(logging.Formatter):
    """Formatter for file output (no colors, more detailed)."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record for file output."""
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        level_name = record.levelname
        module = record.name
        func_name = record.funcName
        line_no = record.lineno
        
        # Build context string
        context_parts = []
        if hasattr(record, 'request_id'):
            context_parts.append(f"req_id={record.request_id}")
        if hasattr(record, 'user_id'):
            context_parts.append(f"user_id={record.user_id}")
        if hasattr(record, 'job_id'):
            context_parts.append(f"job_id={record.job_id}")
        
        context_str = f" [{', '.join(context_parts)}]" if context_parts else ""
        
        # Format message
        message = record.getMessage()
        
        formatted = (
            f"[{timestamp}] [{level_name:8}] [{module}:{func_name}:{line_no}]"
            f"{context_str} {message}"
        )
        
        # Add exception info if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        
        return formatted


# Global logger cache
_loggers: Dict[str, logging.Logger] = {}
_logging_configured = False


def _setup_logging():
    """Setup root logger with console and optional file handlers."""
    global _logging_configured
    
    if _logging_configured:
        return
    
    try:
        from backend.api.utils.config_loader import get_config
        config = get_config()
    except ImportError:
        # Fallback if config loader not available
        log_level = logging.INFO
        log_file = None
        debug_mode = False
    else:
        # Get log level from config or environment
        log_level_str = getattr(config.api, 'log_level', None) or os.getenv('LOG_LEVEL', 'INFO')
        log_level = getattr(logging, log_level_str.upper(), logging.INFO)
        
        # Get log file path from config or environment
        log_file = getattr(config.api, 'log_file', None) or os.getenv('LOG_FILE', None)
        
        # Debug mode affects log level
        debug_mode = config.api.debug
        if debug_mode:
            log_level = logging.DEBUG
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = ColoredFormatter()
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (only if log file is configured)
    if log_file:
        log_path = Path(log_file)
        # Create log directory if it doesn't exist
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_formatter = FileFormatter()
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the given module name.
    
    This function implements a singleton-like pattern where loggers
    are cached and reused. The root logger is configured on first call.
    
    Args:
        name: Logger name (typically __name__ of the calling module)
    
    Returns:
        logging.Logger: Configured logger instance
    
    Example:
        logger = get_logger(__name__)
        logger.info("Processing request")
        logger.error("Error occurred", exc_info=True)
        logger.info("Job started", extra={"job_id": 123, "user_id": 456})
    """
    # Setup logging on first call
    if not _logging_configured:
        _setup_logging()
    
    # Return cached logger or create new one
    if name not in _loggers:
        logger = logging.getLogger(name)
        _loggers[name] = logger
    
    return _loggers[name]


def reset_logging():
    """
    Reset logging configuration.
    
    Useful for testing when you need to reconfigure logging
    with different settings.
    """
    global _logging_configured, _loggers
    
    # Clear all handlers and close file handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()  # Close file handlers to release file locks
        root_logger.removeHandler(handler)
    
    # Also close handlers on child loggers
    for logger in _loggers.values():
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
    
    # Reset state
    _logging_configured = False
    _loggers.clear()


# Import os for fallback in _setup_logging
import os
