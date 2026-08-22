"""Timestamp utilities for domain objects."""
from __future__ import annotations

from datetime import datetime
from aegis.clock import system_clock
from aegis.clock.utc import ensure_utc

class Timestamp:
    """Helpers around timezone-aware UTC timestamps."""

    @staticmethod
    def normalize(dt: datetime | None) -> datetime:
        """Normalize a datetime to timezone-aware UTC.

        If dt is None, returns current UTC time via the Clock service.
        """
        return system_clock.now() if dt is None else ensure_utc(dt)
