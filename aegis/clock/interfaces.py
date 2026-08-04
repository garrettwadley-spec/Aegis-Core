"""Clock interfaces (protocols) for type checking."""
from __future__ import annotations

from typing import Protocol
from datetime import datetime

class ClockInterface(Protocol):
    """Protocol describing the public Clock service API."""

    def now(self) -> datetime:
        ...

    def monotonic(self) -> float:
        ...

    def sequence(self) -> int:
        ...

    def mode(self) -> str:
        ...

    def set_mode(self, mode: str, **kwargs) -> None:
        ...
