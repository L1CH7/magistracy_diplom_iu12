import sys
from loguru import logger

def configure_loguru(service_name: str, log_level: str = "INFO", log_to_file: bool = False, stdout: bool = True):
    logger.remove()
    
    if stdout:
        # Format matches .agent/rules/02_logging.md: [YYYY.MM.DD HH:MM:SS.mmm] {thread_id} LEVEL Message
        # We simulate thread_id with process/thread names if actual ID is not available in default extras, 
        # but loguru's {thread.name} or {thread.id} works.
        logger.add(sys.stdout, level=log_level, format="<green>[{time:YYYY.MM.DD HH:mm:ss.SSS}]</green> <cyan>{{{thread.id}}}</cyan> <level>{level: <8}</level> <level>{message}</level>")
        
    if log_to_file:
        logger.add(f"logs/{service_name}.log", rotation="500 MB", level=log_level, compression="zip")

import logging

class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_uvicorn_logging():
    """Configure Uvicorn to use Loguru."""
    # Intercept everything
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logging.INFO)

    # Remove all existing handlers for uvicorn
    for name in logging.root.manager.loggerDict.keys():
        if name.startswith("uvicorn"):
             logging.getLogger(name).handlers = []

    # Assign intercept handler to uvicorn loggers
    logging.getLogger("uvicorn").handlers = [InterceptHandler()]
    logging.getLogger("uvicorn.access").handlers = [InterceptHandler()]
