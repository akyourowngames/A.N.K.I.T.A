import time
import logging
from typing import Callable, TypeVar

logger = logging.getLogger("J.A.R.V.I.S")
T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    max_retries: int = 2,
    initial_delay: float = 0.5,
) -> T:
    last_exc: Exception = RuntimeError("with_retry called with max_retries < 1")

    for attempt in range(max_retries):
        try:
            return fn()

        except Exception as e:
            last_exc = e

            if attempt < max_retries - 1:
                logger.debug("[RETRY] Attempt %d/%d failed: %s - retrying in %.1fs",
                             attempt + 1, max_retries, e, initial_delay)
                time.sleep(initial_delay)

            else:
                logger.debug("[RETRY] Attempt %d/%d failed: %s - giving up",
                             attempt + 1, max_retries, e)

    raise last_exc