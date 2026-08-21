"""Dispatcher responsible for delivering events to subscribers.

This module focuses on deterministic, synchronous delivery. There are no
external dependencies and delivery order is preserved as events are
consumed from the internal FIFO queue.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import perf_counter
from typing import Deque, Dict, List, Tuple

from .event import Event
from .subscription import Subscription

@dataclass
class _QueuedEvent:
    event: Event

class Dispatcher:
    """Simple synchronous dispatcher that preserves publish ordering.

    The dispatcher is intentionally simple and deterministic: it delivers
    events to all matching subscribers in the order events were published.
    """

    def __init__(self) -> None:
        self._queue: Deque[_QueuedEvent] = deque()

    def enqueue(self, event: Event) -> None:
        """Add an event to the dispatch queue."""
        self._queue.append(_QueuedEvent(event=event))

    def drain(self, subscriptions: Dict[str, List[Subscription]]) -> Tuple[List[Tuple[Subscription, Event, float]], int]:
        """Drain the queue and deliver events to subscribers.

        Returns a list of tuples (subscription, event, latency_seconds) for
        bookkeeping and an integer count of delivered messages.
        """
        deliveries: List[Tuple[Subscription, Event, float]] = []
        delivered = 0

        while self._queue:
            queued = self._queue.popleft()
            event = queued.event
            start = perf_counter()
            subs = subscriptions.get(event.event_type, [])
            # If no subscribers, skip but continue determinism
            for sub in subs:
                # Synchronous delivery
                sub.subscriber.receive(event)
                delivered += 1
                latency = perf_counter() - start
                deliveries.append((sub, event, latency))
        return deliveries, delivered
