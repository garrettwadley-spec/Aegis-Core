"""Monotonic helpers for the Clock Service."""
from __future__ import annotations

import time
from typing import Callable

def system_monotonic() -> float:
    """Return the system monotonic clock value.

    This function centralizes the use of time.monotonic() so subsystems can
    rely on the ClockService rather than calling the function directly.
    """
    return time.monotonic()
