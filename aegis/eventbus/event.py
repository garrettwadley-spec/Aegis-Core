"""Event definitions for Aegis Event Bus.

Immutable Event objects.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Optional
import uuid

from aegis.clock import system_clock

@dataclass(frozen=True)
class Event:
    """Immutable Event object.

    Attributes:
        event_id: Unique identifier for the event instance.
        event_type: Logical type name of the event.
        payload: Event payload (user-defined structure).
        created_at: UTC timestamp when the event was created.
        sequence_number: Deterministic sequence number assigned by the EventBus on publish.
        trace_id: Tracing identifier for distributed tracing.
        correlation_id: Correlation identifier for grouping related events.
    """
    event_id: str
    event_type: str
    payload: Any
    created_at: datetime
    sequence_number: Optional[int]
    trace_id: str
    correlation_id: str

    @classmethod
    def create(cls, event_type: str, payload: Any, *, trace_id: Optional[str] = None, correlation_id: Optional[str] = None) -> "Event":
        """Create a new Event with generated identifiers and timestamp.

        sequence_number is intentionally left as None and assigned by EventBus.publish.
        """
        now = system_clock.now()
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            payload=payload,
            created_at=now,
            sequence_number=None,
            trace_id=trace_id or str(uuid.uuid4()),
            correlation_id=correlation_id or str(uuid.uuid4()),
        )

    def with_sequence(self, sequence_number: int) -> "Event":
        """Return a new Event instance with sequence_number set.

        Because Event is immutable, this helper returns a copy with the new value.
        """
        return replace(self, sequence_number=sequence_number)
