"""Server startup with unified logging configuration."""

import logging
import sys
import uvicorn
from src.utils.logger import configure_structlog, setup_logger

if __name__ == "__main__":
    # Configure unified logging FIRST
    configure_structlog(log_level="INFO")
    
    log = setup_logger(__name__)
    
    # Redirect stdlib logging to structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.CRITICAL,  # Only critical from stdlib
    )
    
    # Completely disable uvicorn access logs
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.disabled = True
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False
    
    # Disable uvicorn general logs
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.disabled = True
    uvicorn_logger.handlers = []
    uvicorn_logger.propagate = False
    
    log.info("Starting server", host="0.0.0.0", port=8000)
    
    # Start uvicorn
    uvicorn.run(
        "src.server.app:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        access_log=False,
        log_level="critical",
    )
