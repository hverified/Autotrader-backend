# app/utils/decorators.py
from functools import wraps
from app.utils.logger import logger


def job_runner(job_name: str):
    """
    A decorator for APScheduler jobs to handle logging and error catching.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger.info(f"Starting scheduled job: '{job_name}'...")
            try:
                result = await func(*args, **kwargs)
                logger.info(f"Successfully completed scheduled job: '{job_name}'.")
                return result
            except Exception as e:
                logger.error(
                    f"Error executing scheduled job '{job_name}': {e}", exc_info=True
                )

        return wrapper

    return decorator
