"""Receipt returned by publish operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

@dataclass
class Receipt:
    """Acknowledgement returned by EventBus.publish.

    Attributes:
        event_id: The published event's id.
        delivery_status: "queued" or "dispatched" depending on dispatch state.
        subscriber_count: Number of subscribers targeted for this event.
        latency: Observed latency in seconds for dispatch (0.0 if not dispatched yet).
    """
    event_id: str
    delivery_status: Literal["queued", "dispatched"]
    subscriber_count: int
    latency: float
