"""
Common loguru configuration for all services.

Usage:
    from src.utils.loguru_config import configure_loguru
    
    configure_loguru(service_name="data-processor")
"""

import sys
from loguru import logger as _logger


def configure_loguru(
    service_name: str = "service",
    log_level: str = "DEBUG",
    log_to_file: bool = True,
    stdout: bool = True
) -> None:
    """
    Configure loguru with common format for all services.
    
    Args:
        service_name: Service name for log files
        log_level: Log level (DEBUG/INFO/WARNING/ERROR)
        log_to_file: Enable file logging
        stdout: Enable stdout logging
    """
    # Remove default handler
    _logger.remove()
    
    # Standard format according to 04-logging-standards.md
    # [YYYY.MM.DD HH:MM:SS.mmm] {thread_id} LEVEL Message
    
    # Map levels to single-letter icons
    def format_record(record):
        level_map = {
            "TRACE": "T",
            "DEBUG": "D",
            "INFO": "I",
            "SUCCESS": "I",  # Map SUCCESS to INFO
            "WARNING": "W",
            "ERROR": "E",
            "CRITICAL": "F"
        }
        record["extra"]["level_icon"] = level_map.get(
            record["level"].name, record["level"].name[0]
        )
        return record
    
    log_format = (
        "[<green>{time:YYYY.MM.DD HH:mm:ss.SSS}</green>] "
        "{{<cyan>{thread.id:x}</cyan>}} "
        "<level>{extra[level_icon]}</level> "
        "<level>{message}</level>"
    )
    
    # Apply format patching globally
    _logger.configure(patcher=format_record)
    
    # Stdout handler
    if stdout:
        _logger.add(
            sys.stdout,
            format=log_format,
            level=log_level,
            colorize=True,
            backtrace=True,
            diagnose=True
        )
    
    # File handler
    if log_to_file:
        _logger.add(
            f"logs/{service_name}.log",
            format=log_format,
            level=log_level,
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            backtrace=True,
            diagnose=True
        )
    
    _logger.info(f"Loguru configured for {service_name}")
