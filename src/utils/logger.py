"""Unified structured logging for the entire project.

Format:
[YYYY.MM.DD HH:MM:SS.mmm] {thread_id} LEVEL [module.func:line] msg key=val

Uses structlog for structured logging with console and file output.
"""

import logging
import threading
import sys
from pathlib import Path
import structlog
from structlog.types import EventDict, WrappedLogger


def add_thread_info(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add thread ID to log context."""
    thread_ident = threading.current_thread().ident
    event_dict["thread"] = f"0x{thread_ident:x}" if thread_ident else "0x0"
    return event_dict


def add_caller_info(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add caller module, function, and line number."""
    frame = sys._getframe(5)  # Adjust depth to skip structlog internals
    module = frame.f_globals.get('__name__', 'unknown')
    func = frame.f_code.co_name
    line = frame.f_lineno
    event_dict["caller"] = f"{module}.{func}:{line}"
    return event_dict


def format_console_line(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> str:
    """Format log line for console output.
    
    Format: [YYYY.MM.DD HH:MM:SS.mmm] {thread} LEVEL [caller] msg k=v
    """
    from datetime import datetime
    
    timestamp = datetime.now().strftime('%Y.%m.%d %H:%M:%S.%f')[:-3]
    thread = event_dict.pop('thread', '0x0')
    
    # Map structlog levels to single char
    level_map = {
        'debug': 'D',
        'info': 'I',
        'warning': 'W',
        'error': 'E',
        'critical': 'F',
    }
    level = level_map.get(event_dict.pop('level', 'info'), 'I')
    
    caller = event_dict.pop('caller', 'unknown')
    event = event_dict.pop('event', '')
    
    # Build key=value pairs for extra context
    extras = ' '.join(f"{k}={v}" for k, v in event_dict.items())
    
    line = f"[{timestamp}] {{{thread}}} {level} [{caller}] {event}"
    if extras:
        line += f" {extras}"
    
    return line


def configure_structlog(log_level: str = "INFO"):
    """Configure structlog for entire application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Ensure log directory
    log_dir = Path('.agent_dir/logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure stdlib logging (for libraries)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            add_thread_info,
            add_caller_info,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            format_console_line,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_logger(
    name: str, level: str = "INFO"
) -> structlog.stdlib.BoundLogger:
    """Get configured structlog logger.
    
    Args:
        name: Logger name (usually __name__)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Configured structlog logger
    
    Usage:
        log = setup_logger(__name__)
        log.info("message", key1=value1, key2=value2)
        log.error("error occurred", error=str(e), code=500)
    """
    # Configure on first use
    if not structlog.is_configured():
        configure_structlog(level)
    
    return structlog.get_logger(name)
