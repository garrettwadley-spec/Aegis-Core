"""Correlation context helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
import uuid

@dataclass(frozen=True)
class CorrelationContext:
    """Holds correlation identifiers for grouping related domain objects."""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
