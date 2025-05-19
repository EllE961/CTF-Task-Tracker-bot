#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logging(log_level="INFO"):
    """
    Configure logging with console and file handlers.
    
    Args:
        log_level: The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        The configured logger
    """
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers if any
    if logger.handlers:
        for handler in logger.handlers:
            logger.removeHandler(handler)
    
    # Create a console handler with a more detailed formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    logger.addHandler(console_handler)
    
    # Create a file handler with rotation
    log_file = log_dir / 'bot.log'
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,  # 1 MB
        backupCount=5,
        encoding='utf-8'
    )
    # More detailed formatter for file logs
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)  # Always log debug to file
    logger.addHandler(file_handler)
    
    # Create a separate error log file for warnings and above
    error_log_file = log_dir / 'error.log'
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=1_000_000,  # 1 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(file_formatter)
    logger.addHandler(error_handler)
    
    # Log startup information
    logger.info(f"Logging initialized at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Console log level: {log_level.upper()}")
    logger.info(f"File log level: DEBUG")
    logger.info(f"Log files: {log_file}, {error_log_file}")
    
    return logger

class ContextFilter(logging.Filter):
    """Add contextual information to log records."""
    
    def __init__(self, **kwargs):
        super().__init__()
        self.extra = kwargs
    
    def filter(self, record):
        for key, value in self.extra.items():
            setattr(record, key, value)
        return True

def add_context_to_logger(logger, **kwargs):
    """Add context filter to logger."""
    logger.addFilter(ContextFilter(**kwargs))
    
def log_command(logger, cmd_name, interaction, *args, **kwargs):
    """Log command execution with context."""
    guild = interaction.guild.name if interaction.guild else "DM"
    user = f"{interaction.user.name}#{interaction.user.discriminator}"
    
    arg_str = ", ".join([f"{a}" for a in args])
    kwarg_str = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
    all_args = []
    if arg_str:
        all_args.append(arg_str)
    if kwarg_str:
        all_args.append(kwarg_str)
    
    params = f" | Args: {', '.join(all_args)}" if all_args else ""
    
    logger.info(f"Command: /{cmd_name} | User: {user} | Guild: {guild}{params}")

def log_button(logger, btn_name, interaction, entity_id=None):
    """Log button click with context."""
    guild = interaction.guild.name if interaction.guild else "DM"
    user = f"{interaction.user.name}#{interaction.user.discriminator}"
    
    entity_info = f" | Entity: #{entity_id}" if entity_id else ""
    
    logger.info(f"Button: {btn_name} | User: {user} | Guild: {guild}{entity_info}") 