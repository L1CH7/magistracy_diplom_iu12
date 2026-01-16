import sys
from loguru import logger

def configure_loguru(service_name: str, log_level: str = "INFO", log_to_file: bool = False, stdout: bool = True):
    logger.remove()
    
    if stdout:
        logger.add(sys.stdout, level=log_level, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
        
    if log_to_file:
        logger.add(f"logs/{service_name}.log", rotation="500 MB", level=log_level, compression="zip")
