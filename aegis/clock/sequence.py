"""Sequence number generator for the Clock Service."""
from __future__ import annotations

from threading import Lock
from typing import Optional

class SequenceGenerator:
    """Thread-safe monotonic sequence number generator.

    Guarantees:
    - Global monotonic increasing integers within the process lifetime.
    - Never repeats or decreases while the process runs.

    Behavior:
    - If seed is None (default), sequences start at 1 (first next() returns 1).
    - If seed is provided (e.g., seed=100), the first next() will return seed.
      Internally the counter is initialized to seed - 1 so callers observe the
      literal seed on the first next() call.
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        self._lock = Lock()
        if seed is None:
            # Start at 0 so first next() -> 1
            self._value = 0
        else:
            # Initialize to seed - 1 so first next() returns seed
            self._value = seed - 1

    def next(self) -> int:
        """Return the next monotonic sequence number."""
        with self._lock:
            self._value += 1
            return self._value

    def current(self) -> int:
        """Return current value without incrementing."""
        with self._lock:
            return self._value
