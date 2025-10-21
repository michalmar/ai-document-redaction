"""Retry logic with exponential backoff for Azure API calls."""

import asyncio
import logging
from typing import Tuple, Callable, Any
from azure.core.exceptions import HttpResponseError, ServiceRequestError, ServiceResponseError

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 30.0  # seconds


async def retry_with_backoff(
    func: Callable,
    *args,
    max_retries: int = MAX_RETRIES,
    initial_delay: float = INITIAL_RETRY_DELAY,
    max_delay: float = MAX_RETRY_DELAY,
    **kwargs
) -> Tuple[bool, Any, str]:
    """
    Execute an async function with exponential backoff retry logic.
    
    Args:
        func: Async function to execute
        *args: Positional arguments for func
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        **kwargs: Keyword arguments for func
        
    Returns:
        Tuple of (success, result, error_message)
    """
    delay = initial_delay
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            result = await func(*args, **kwargs)
            return True, result, ""
        except (HttpResponseError, ServiceRequestError, ServiceResponseError) as e:
            last_error = e
            
            # Check if error is retryable
            is_retryable = False
            if isinstance(e, HttpResponseError):
                # Retry on 429 (rate limit), 500-599 (server errors)
                status_code = getattr(e, 'status_code', None)
                is_retryable = status_code in (429, 500, 502, 503, 504) or status_code is None
            else:
                # Network errors are retryable
                is_retryable = True
            
            if not is_retryable or attempt >= max_retries:
                error_msg = str(e)
                if hasattr(e, 'message'):
                    error_msg = e.message
                logger.warning(f"Non-retryable error or max retries exceeded: {error_msg}")
                return False, None, error_msg
            
            # Log retry attempt
            logger.debug(f"Retry attempt {attempt + 1}/{max_retries} after error: {e}")
            
            # Wait before retry with exponential backoff
            await asyncio.sleep(min(delay, max_delay))
            delay *= 2  # Exponential backoff
            
        except Exception as e:
            # Non-Azure exceptions are not retried
            error_msg = str(e)
            logger.error(f"Non-retryable exception: {error_msg}")
            return False, None, error_msg
    
    # Should not reach here, but handle gracefully
    return False, None, str(last_error) if last_error else "Unknown error"
