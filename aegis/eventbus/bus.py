"""Core EventBus implementation.

Public interface (required):
- publish(event)
- subscribe(event_type, subscriber)
- unsubscribe(subscription)
- dispatch()

Guarantees:
- Immutable Event objects (Event is frozen).
- Deterministic ordering via internal sequence numbers and FIFO queue.
- Publish/Subscribe model with multiple subscribers supported.
- No external dependencies.
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from time import perf_counter
import uuid

from .event import Event
from .receipt import Receipt
from .subscription import Subscription
from .dispatcher import Dispatcher
from .subscriber import Subscriber

class EventBus:
    """EventBus coordinating publish/subscribe/dispatch.

    Thread-safety: simple Lock protects publishers and subscriber maps. The
    dispatch operation is synchronous and deterministic: events are assigned
    monotonic sequence numbers on publish and delivered in FIFO order.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscriptions: Dict[str, List[Subscription]] = {}
        self._sequence_counter = 0
        self._dispatcher = Dispatcher()

    def _next_sequence(self) -> int:
        with self._lock:
            self._sequence_counter += 1
            return self._sequence_counter

    def publish(self, event: Event) -> Receipt:
        """Publish an Event to the bus.

        The EventBus assigns a deterministic sequence number and queues the
        event for dispatch. Returns a Receipt acknowledging queuing.
        """
        if event.sequence_number is not None:
            # Respect provided sequence_number but ensure monotonicity by
            # assigning a new one if lower than current counter.
            with self._lock:
                if event.sequence_number <= self._sequence_counter:
                    seq = self._next_sequence()
                else:
                    self._sequence_counter = event.sequence_number
                    seq = event.sequence_number
        else:
            seq = self._next_sequence()

        event_with_seq = event.with_sequence(seq)

        # Count targeted subscribers deterministically
        target_subs = list(self._subscriptions.get(event_with_seq.event_type, []))
        subscriber_count = len(target_subs)

        # Enqueue for dispatch
        self._dispatcher.enqueue(event_with_seq)

        receipt = Receipt(
            event_id=event_with_seq.event_id,
            delivery_status="queued",
            subscriber_count=subscriber_count,
            latency=0.0,
        )
        return receipt

    def subscribe(self, event_type: str, subscriber: Subscriber) -> Subscription:
        """Subscribe a Subscriber to an event_type.

        Returns a Subscription object which can be used to unsubscribe.
        """
        sub = Subscription(subscription_id=str(uuid.uuid4()), event_type=event_type, subscriber=subscriber)
        with self._lock:
            self._subscriptions.setdefault(event_type, []).append(sub)
        return sub

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Remove a subscription. Returns True if removed, False if not found."""
        with self._lock:
            subs = self._subscriptions.get(subscription.event_type, [])
            for i, s in enumerate(subs):
                if s.subscription_id == subscription.subscription_id:
                    del subs[i]
                    return True
        return False

    def dispatch(self) -> List[Receipt]:
        """Dispatch queued events to subscribers synchronously.

        Returns a list of Receipts updated to reflect dispatch status and
        observed latencies per event (average across subscribers).
        """
        # Drain dispatcher; it will call subscriber.receive synchronously.
        deliveries, delivered = self._dispatcher.drain(self._subscriptions)

        # Aggregate deliveries into receipts per event_id
        receipt_map: Dict[str, Dict[str, Any]] = {}
        for sub, event, latency in deliveries:
            r = receipt_map.setdefault(event.event_id, {"latencies": [], "subscriber_count": 0})
            r["latencies"].append(latency)
            r["subscriber_count"] += 1

        receipts: List[Receipt] = []
        for event_id, data in receipt_map.items():
            avg_latency = sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else 0.0
            receipts.append(Receipt(event_id=event_id, delivery_status="dispatched", subscriber_count=data["subscriber_count"], latency=avg_latency))

        return receipts
