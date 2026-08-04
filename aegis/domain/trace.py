"""Trace context helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
import uuid

@dataclass(frozen=True)
class TraceContext:
    """Holds tracing identifiers used for distributed tracing.

    Fields:
        trace_id: unique trace identifier
    """
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
