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
