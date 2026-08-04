"""Publisher helpers for Event Bus."""
from __future__ import annotations

from typing import Any
from .event import Event
from .receipt import Receipt

class Publisher:
    """Lightweight publisher utility.

    Publisher exists mainly for conceptual separation. The EventBus governs
    sequence numbers and queueing; Publisher provides a convenience wrapper
    for creating and publishing events with typed payloads.
    """

    def __init__(self, bus: "EventBus") -> None:  # type: ignore[name-defined]
        self._bus = bus

    def publish(self, event: Event) -> Receipt:
        """Publish an Event instance through the associated EventBus."""
        return self._bus.publish(event)
