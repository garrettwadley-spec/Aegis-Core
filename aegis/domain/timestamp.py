"""Timestamp utilities for domain objects."""
from __future__ import annotations

from datetime import datetime
from aegis.clock.utc import ensure_utc

class Timestamp:
    """Helpers around timezone-aware UTC timestamps."""

    @staticmethod
    def normalize(dt: datetime | None) -> datetime:
        """Normalize a datetime to timezone-aware UTC.

        If dt is None, returns current UTC time via Clock's utc helper.
        """
        return ensure_utc(dt)
