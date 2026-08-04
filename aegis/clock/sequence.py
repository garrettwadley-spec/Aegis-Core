"""Sequence number generator for the Clock Service."""
from __future__ import annotations

from threading import Lock
from typing import Final

class SequenceGenerator:
    """Thread-safe monotonic sequence number generator.

    Guarantees:
    - Global monotonic increasing integers starting at 1.
    - Never repeats or decreases within the process lifetime.
    """

    def __init__(self, start: int = 0) -> None:
        self._lock = Lock()
        self._value = start

    def next(self) -> int:
        """Return the next monotonic sequence number."""
        with self._lock:
            self._value += 1
            return self._value

    def current(self) -> int:
        """Return current value without incrementing."""
        with self._lock:
            return self._value
