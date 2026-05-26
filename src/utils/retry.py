"""Retry utility for handling transient errors."""

import time
import functools
from typing import Callable, Type, Tuple, Optional, Any
from playwright.sync_api import TimeoutError as PlaywrightTimeout


def retry_on_exception(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None
):
    """
    Decorator to retry a function on specific exceptions.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exception types to catch and retry
        on_retry: Optional callback function(attempt, exception) called on each retry
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(attempt, e)
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        # Last attempt failed, raise the exception
                        raise
                except Exception as e:
                    # Don't retry on other exceptions
                    raise
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


def retry_playwright_operation(
    max_attempts: int = 3,
    delay: float = 1.0,
    on_retry: Optional[Callable[[int, Exception], None]] = None
):
    """
    Decorator specifically for Playwright operations that may timeout.
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Delay between retries in seconds
        on_retry: Optional callback function(attempt, exception) called on each retry
    """
    return retry_on_exception(
        max_attempts=max_attempts,
        delay=delay,
        backoff=1.5,
        exceptions=(PlaywrightTimeout, TimeoutError, ConnectionError),
        on_retry=on_retry
    )


def retry_network_operation(
    max_attempts: int = 3,
    delay: float = 1.0,
    on_retry: Optional[Callable[[int, Exception], None]] = None
):
    """
    Decorator for network operations (requests, downloads).
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Delay between retries in seconds
        on_retry: Optional callback function(attempt, exception) called on each retry
    """
    import requests
    return retry_on_exception(
        max_attempts=max_attempts,
        delay=delay,
        backoff=2.0,
        exceptions=(
            requests.exceptions.RequestException,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            ConnectionError,
            TimeoutError
        ),
        on_retry=on_retry
    )


