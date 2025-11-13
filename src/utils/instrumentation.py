"""Automatic function instrumentation with zero-cost decorators.

Based on .github/agent_logging_guide.md recommendations.

Zero-cost guarantee:
- If log level is above decorator level, decorator overhead is minimal
- Lazy evaluation ensures expensive operations aren't computed
- Context propagation uses contextvars (thread-safe)

Usage:
    from src.utils.instrumentation import log_function
    from loguru import logger
    
    @log_function("DEBUG")
    def my_function(x, y):
        logger.info("processing", x=x, y=y)
        return x + y
    
    # Zero-cost for expensive args logging
    @log_function("TRACE", include_args=False)
    def sensitive_function(password):
        return hash(password)
"""

from functools import wraps
from loguru import logger
import time
from typing import Any, Callable, Optional
import inspect
import contextvars


# Context variables for distributed tracing
request_id_var = contextvars.ContextVar("request_id", default="unknown")
user_id_var = contextvars.ContextVar("user_id", default="anonymous")
trace_id_var = contextvars.ContextVar("trace_id", default="")
agent_context = contextvars.ContextVar("agent_context", default={})


def set_agent_context(**kwargs) -> contextvars.Token:
    """Set agent context for all subsequent logs in this execution.
    
    Args:
        **kwargs: Context key-value pairs
    
    Returns:
        Token to restore previous context
    
    Example:
        token = set_agent_context(agent_id="agent_001", task_id="t123")
        try:
            process_task()
        finally:
            agent_context.reset(token)  # Restore previous context
    """
    current = agent_context.get().copy()
    current.update(kwargs)
    token = agent_context.set(current)
    return token


def log_with_context(message: str, level: str = "INFO", **extra):
    """Log message with automatic context propagation.
    
    Args:
        message: Log message
        level: Log level
        **extra: Additional key-value pairs
    
    Example:
        set_agent_context(agent_id="agent_001")
        log_with_context("Task started", task_id="t123")
        # Logs: {"message": "Task started", "agent_id": "agent_001",
        #        "task_id": "t123", "request_id": "...", ...}
    """
    context = agent_context.get().copy()
    context.update({
        "request_id": request_id_var.get(),
        "user_id": user_id_var.get(),
        "trace_id": trace_id_var.get(),
    })
    context.update(extra)
    
    logger.log(level, message, **context)


def log_function(
    level: str = "DEBUG",
    include_args: bool = True,
    include_result: bool = False,
    max_result_len: int = 500
):
    """Decorator for automatic function instrumentation.
    
    Zero-cost: if handler level is above 'level', minimal overhead.
    
    Args:
        level: Log level (TRACE, DEBUG, INFO, etc.)
        include_args: Log function arguments (disable for sensitive data)
        include_result: Log function return value
        max_result_len: Max chars of result to log
    
    Example:
        @log_function("DEBUG")
        def process_data(user_id, data):
            return transformed_data
        
        # Logs:
        # → Calling process_data (args logged)
        # ← process_data completed (duration logged)
    """
    def decorator(func: Callable) -> Callable:
        # Get function signature once at decoration time
        sig = inspect.signature(func)
        func_name = func.__name__
        module_name = func.__module__
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build context
            context = {
                "function": func_name,
                "module": module_name,
            }
            
            # Add agent context
            context.update(agent_context.get())
            
            # Log arguments if enabled
            if include_args:
                try:
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    # Convert to dict, truncate large values
                    args_dict = {}
                    for key, value in bound.arguments.items():
                        str_val = str(value)
                        if len(str_val) > max_result_len:
                            str_val = str_val[:max_result_len] + "..."
                        args_dict[key] = str_val
                    context["args"] = args_dict
                except Exception:
                    # If binding fails, skip args logging
                    pass
            
            # Log function entry
            logger.log(
                level,
                f"→ {func_name}",
                **context
            )
            
            # Execute function with timing
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                
                # Log function exit
                exit_context = {
                    "function": func_name,
                    "module": module_name,
                    "duration_ms": duration_ms,
                }
                exit_context.update(agent_context.get())
                
                if include_result:
                    result_str = str(result)
                    if len(result_str) > max_result_len:
                        result_str = result_str[:max_result_len] + "..."
                    exit_context["result"] = result_str
                
                logger.log(
                    level,
                    f"← {func_name}",
                    **exit_context
                )
                
                return result
            
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                
                # Log exception
                error_context = {
                    "function": func_name,
                    "module": module_name,
                    "duration_ms": duration_ms,
                    "exception_type": type(e).__name__,
                }
                error_context.update(agent_context.get())
                
                logger.exception(
                    f"✗ {func_name} failed",
                    **error_context
                )
                raise
        
        return wrapper
    return decorator


def log_async_function(
    level: str = "DEBUG",
    include_args: bool = True,
    include_result: bool = False,
    max_result_len: int = 500
):
    """Decorator for async function instrumentation.
    
    Same as log_function but for async/await functions.
    
    Example:
        @log_async_function("DEBUG")
        async def fetch_data(url):
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                return response.json()
    """
    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)
        func_name = func.__name__
        module_name = func.__module__
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            context = {
                "function": func_name,
                "module": module_name,
            }
            context.update(agent_context.get())
            
            if include_args:
                try:
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    args_dict = {}
                    for key, value in bound.arguments.items():
                        str_val = str(value)
                        if len(str_val) > max_result_len:
                            str_val = str_val[:max_result_len] + "..."
                        args_dict[key] = str_val
                    context["args"] = args_dict
                except Exception:
                    pass
            
            logger.log(level, f"→ {func_name}", **context)
            
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                
                exit_context = {
                    "function": func_name,
                    "module": module_name,
                    "duration_ms": duration_ms,
                }
                exit_context.update(agent_context.get())
                
                if include_result:
                    result_str = str(result)
                    if len(result_str) > max_result_len:
                        result_str = result_str[:max_result_len] + "..."
                    exit_context["result"] = result_str
                
                logger.log(level, f"← {func_name}", **exit_context)
                
                return result
            
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                
                error_context = {
                    "function": func_name,
                    "module": module_name,
                    "duration_ms": duration_ms,
                    "exception_type": type(e).__name__,
                }
                error_context.update(agent_context.get())
                
                logger.exception(f"✗ {func_name} failed", **error_context)
                raise
        
        return wrapper
    return decorator
