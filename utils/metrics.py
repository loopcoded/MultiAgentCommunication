# utils/metrics.py

import time
import logging
import traceback
from functools import wraps

# Create directory if not exists
import os
os.makedirs("logs", exist_ok=True)

# Setup a common metrics logger
worker_logger = logging.getLogger("agent_metrics")
worker_logger.setLevel(logging.INFO)

if not worker_logger.handlers:
    handler = logging.FileHandler("logs/agent_metrics.log", mode='a', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s || %(levelname)s || %(message)s')
    handler.setFormatter(formatter)
    worker_logger.addHandler(handler)


def track_metrics(func):
    """
    Decorator to track execution time, success, and errors for async agent methods.
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        start = time.time()
        task_name = f"{self.__class__.__name__}.{func.__name__}"
        try:
            result = await func(self, *args, **kwargs)
            duration = time.time() - start
            worker_logger.info(f"[SUCCESS] {task_name} executed in {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            worker_logger.error(f"[FAILURE] {task_name} failed in {duration:.2f}s: {e}")
            worker_logger.debug(traceback.format_exc())
            raise
    return wrapper
