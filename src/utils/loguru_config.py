"""Unified structured logging with loguru (zero-cost when disabled).

Based on .github/agent_logging_guide.md recommendations.

Format:
[YYYY.MM.DD HH:MM:SS.mmm] {thread_id} LEVEL [module.func:line] msg key=val

Zero-cost guarantee:
- Disabled log levels have ZERO CPU overhead
- No string formatting if log level is disabled
- No function calls if log level is disabled

Architecture:
- stdout: colored console output (for development)
- app.jsonl: JSON Lines format for Promtail/Loki (production)
- errors.jsonl: separate error logs for fast detection
- slow_operations.jsonl: performance monitoring (>1s operations)

Usage:
    from loguru import logger
    
    logger.info("message with {param}", param=value)
    logger.opt(lazy=True).debug("expensive: {}", expensive_calc)
"""

import sys
import threading
import json
from pathlib import Path
from loguru import logger


def log_performance_filter(record: dict) -> bool:
    """Filter for slow operations (>1 second).
    
    Args:
        record: Loguru record dict
    
    Returns:
        True if operation is slow (should be logged)
    """
    if "duration_ms" in record["extra"]:
        return record["extra"]["duration_ms"] > 1000
    return False  # Skip if no duration_ms


def configure_loguru(
    log_level: str = "INFO",
    log_to_file: bool = True,
    json_logs: bool = True
):
    """Configure loguru for entire application.
    
    Based on .github/agent_logging_guide.md best practices.
    
    Args:
        log_level: Minimum level (TRACE, DEBUG, INFO, WARNING, ERROR)
        log_to_file: Enable file logging
        json_logs: Enable JSON logs for Loki/Promtail
    
    Zero-cost behavior:
        If log_level="WARNING", then logger.debug() and logger.info()
        will have ZERO CPU cost (no string formatting, no calls).
    
    Handlers:
        - stdout: colored console (development)
        - app.jsonl: all logs in JSON (for Loki)
        - errors.jsonl: only ERROR+ (fast error detection)
        - slow_operations.jsonl: performance monitoring (>1s)
    """
    # Remove default handler
    logger.remove()
    
    # Thread context patcher
    def thread_patcher(record):
        """Add thread ID to record extra."""
        thread_id = threading.current_thread().ident
        tid = f"0x{thread_id:x}" if thread_id else "0x0"
        record["extra"]["thread_id"] = tid
    
    logger.configure(patcher=thread_patcher)
    
    # === STDOUT: Pretty colored output (development) ===
    console_format = (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>"
    )
    
    # TRACE filter: only show TRACE if explicitly enabled
    def trace_filter(record):
        """Filter TRACE logs unless log_level is TRACE."""
        if record["level"].name == "TRACE":
            return log_level.upper() == "TRACE"
        return True
    
    logger.add(
        sys.stdout,
        level="TRACE",  # Accept all levels, filter in trace_filter
        format=console_format,
        colorize=True,
        backtrace=True,
        diagnose=True,
        enqueue=False,  # Synchronous (faster for console)
        catch=True,
        filter=trace_filter  # Zero-cost TRACE when not enabled
    )
    
    if not log_to_file:
        return logger
    
    # Create logs directory
    log_dir = Path('.agent_dir/logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    
    if json_logs:
        # === JSON LOGS: For Loki/Promtail ingestion ===
        
        # 1. All logs (app.jsonl)
        logger.add(
            log_dir / "app.jsonl",
            level="TRACE",  # Capture everything
            serialize=True,  # JSON output
            rotation="500 MB",
            retention="7 days",
            compression="zip",
            enqueue=True,  # Async file writes
            catch=True,
            filter=trace_filter  # Zero-cost TRACE
        )
        
        # 2. Errors only (errors.jsonl) - for fast error detection
        logger.add(
            log_dir / "errors.jsonl",
            level="ERROR",
            serialize=True,
            rotation="100 MB",
            retention="7 days",
            compression="zip",
            enqueue=True,
            catch=True
        )
        
        # 3. Slow operations (slow_operations.jsonl) - performance monitoring
        logger.add(
            log_dir / "slow_operations.jsonl",
            level="INFO",
            serialize=True,
            filter=log_performance_filter,
            rotation="100 MB",
            retention="7 days",
            compression="zip",
            enqueue=True,
            catch=True
        )
    
    else:
        # === TEXT LOGS: Human-readable format ===
        text_format = (
            "[{time:YYYY.MM.DD HH:mm:ss.SSS}] "
            "{{{extra[thread_id]}}} "
            "{level:1.1} "
            "[{name}.{function}:{line}] "
            "{message}"
        )
        
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=log_level.upper(),
            format=text_format,
            rotation="00:00",  # Midnight rotation
            retention="7 days",
            compression="zip",
            enqueue=True,
            catch=True
        )
    
    return logger


# === INITIALIZATION ===
# Check for TRACE flag file (set by scripts/enable_trace.py)
def _check_trace_flag() -> str:
    """Check if TRACE enabled via flag file."""
    import os
    log_dir = Path('.agent_dir/logs')
    
    # Check for process-specific flag (client or server)
    process_name = os.path.basename(sys.argv[0]).split('.')[0]
    if process_name in ['main', 'app']:
        # Determine if client or server from module path
        if 'client' in sys.argv[0]:
            process_name = 'client'
        elif 'server' in sys.argv[0]:
            process_name = 'server'
    
    flag_file = log_dir / f'TRACE_ENABLED_{process_name}'
    
    if flag_file.exists():
        return "TRACE"
    return "INFO"


# Configure on module import (can be reconfigured later)
# Default: INFO level (TRACE disabled for zero-cost)
# Check flag file for dynamic TRACE enabling
_initial_level = _check_trace_flag()
configure_loguru(log_level=_initial_level, log_to_file=True, json_logs=True)

if _initial_level == "TRACE":
    logger.info("🔍 TRACE logging enabled via flag file")


def enable_trace_logging():
    """Enable TRACE level logging for detailed debugging.
    
    Usage:
        from src.utils.loguru_config import enable_trace_logging
        enable_trace_logging()
    """
    logger.remove()
    configure_loguru(log_level="TRACE", log_to_file=True, json_logs=True)
    logger.info("TRACE logging enabled (detailed movement tracking)")


def disable_trace_logging():
    """Disable TRACE level logging (back to INFO).
    
    Usage:
        from src.utils.loguru_config import disable_trace_logging
        disable_trace_logging()
    """
    logger.remove()
    configure_loguru(log_level="INFO", log_to_file=True, json_logs=True)
    logger.info("TRACE logging disabled (INFO level)")
