import asyncio
import inspect

async def execute_with_timeout(func, timeout=10, **kwargs):
    """Execute a function with timeout.
    Args:
        func: The function to execute (can be sync or async)
        timeout: Timeout in seconds
        **kwargs: Arguments to pass to the function
    """
    try:
        # Check if the function is async
        if inspect.iscoroutinefunction(func):
            # For async functions, just await them with timeout
            return await asyncio.wait_for(func(**kwargs), timeout=timeout)
        else:
            # For sync functions, run them in a thread
            return await asyncio.wait_for(
                asyncio.to_thread(func, **kwargs),
                timeout=timeout
            )
    except asyncio.TimeoutError:
        print(f"Timeout executing {func.__name__}")
        raise