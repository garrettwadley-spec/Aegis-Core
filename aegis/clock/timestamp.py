"""Timestamp utilities and wrapping types for Clock Service."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .utc import ensure_utc

def to_timestamp(dt: Optional[datetime] = None) -> datetime:
    """Return a timezone-aware UTC datetime (wrapper around ensure_utc)."""
    return ensure_utc(dt)
