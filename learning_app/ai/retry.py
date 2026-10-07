from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")

_TRANSIENT_MARKERS = (
    "408",
    "409",
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection",
    "overloaded",
    "rate limit",
    "temporarily",
    "timeout",
    "unavailable",
)


def call_with_transient_retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    initial_delay_seconds: float = 1.0,
) -> T:
    """Retry likely transient provider failures with a short exponential delay."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    delay = initial_delay_seconds
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}".lower()
            transient = any(marker in message for marker in _TRANSIENT_MARKERS)
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2

    raise AssertionError("unreachable")
