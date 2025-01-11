import asyncio

def execute_with_timeout(func, timeout=10, **kwargs):
    """Execute a function with timeout.
    Args:
        func: The function to execute
        timeout: Timeout in seconds
        **kwargs: Arguments to pass to the function
    """
    async def _execute():
        try:
            task = asyncio.create_task(
                asyncio.wait_for(
                    asyncio.to_thread(func, **kwargs),
                    timeout=timeout
                )
            )
            return await task
        except asyncio.TimeoutError:
            print(f"Timeout executing {func.__name__}")
            raise

    return _execute()