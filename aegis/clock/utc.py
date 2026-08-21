"""UTC helpers for the Clock Service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime for the current system time."""
    return datetime.now(timezone.utc)

def ensure_utc(dt: Optional[datetime]) -> datetime:
    """Return a timezone-aware UTC datetime. If dt is None, return now.

    If dt is naive, interpret it as UTC.
    """
    if dt is None:
        return utc_now()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
