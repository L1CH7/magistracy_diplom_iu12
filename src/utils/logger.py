import logging
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
import os


class CustomFormatter(logging.Formatter):
    LEVEL_MAP = {
        logging.DEBUG: 'D',
        logging.INFO: 'I',
        logging.WARNING: 'W',
        logging.ERROR: 'E',
        logging.CRITICAL: 'F',
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y.%m.%d %H:%M:%S.%f')[:-3]
        thread_ident = threading.current_thread().ident
        thread_id = f"0x{thread_ident:x}" if thread_ident is not None else "0x0"
        level = self.LEVEL_MAP.get(record.levelno, 'I')
        message = record.getMessage()
        return f"[{timestamp}] {{{thread_id}}} {level} {message}"


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Configure logger with console and rotating file handlers.

    Format: [YYYY.MM.DD HH:MM:SS.mmm] {thread_id} LEVEL Message
    File logs are stored under .agent_dir/logs/{name}.log
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)

    # Ensure log directory
    os.makedirs('.agent_dir/logs', exist_ok=True)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(CustomFormatter())
    logger.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        f'.agent_dir/logs/{name}.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
    )
    file_handler.setFormatter(CustomFormatter())
    logger.addHandler(file_handler)

    return logger
