"""Centralized logging configuration using structlog."""
import logging
import logging.config
from pathlib import Path

import structlog


def add_call_site_info(logger, method_name, event_dict):
    """Add function name and line number to log records."""
    # Get the frame that called the logger
    frame = event_dict.get("_frame")
    if frame:
        event_dict["func"] = frame.f_code.co_name
        event_dict["lineno"] = frame.f_lineno
    return event_dict


def setup_logging(
    log_file: str = "logs/navigation_mas.log",
    level: str = "DEBUG"
):
    """Setup structured logging for the entire application.
    
    Args:
        log_file: Path to log file (relative to project root)
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Timestamper
    timestamper = structlog.processors.TimeStamper(fmt="ISO", utc=False)
    
    # Shared processors for both console and file
    pre_chain = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ],
        ),
        structlog.stdlib.ExtraAdder(),
        timestamper,
    ]
    
    # Configure standard library logging first
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.dev.ConsoleRenderer(colors=False),
                ],
                "foreign_pre_chain": pre_chain,
            },
            "colored": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.dev.ConsoleRenderer(colors=True),
                ],
                "foreign_pre_chain": pre_chain,
            },
        },
        "handlers": {
            "console": {
                "level": level,
                "class": "logging.StreamHandler",
                "formatter": "colored",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "level": level,
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file,
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "formatter": "plain",
            },
        },
        "loggers": {
            "": {
                "handlers": ["console", "file"],
                "level": level,
                "propagate": True,
            }
        }
    })
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ],
            ),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            timestamper,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)
