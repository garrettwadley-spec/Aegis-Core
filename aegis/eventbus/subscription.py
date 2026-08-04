"""Subscription container used to manage subscriptions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .subscriber import Subscriber

@dataclass(frozen=True)
class Subscription:
    """Represents a subscription to an event type.

    Attributes:
        subscription_id: Unique id for the subscription.
        event_type: Event type subscribed to.
        subscriber: The subscriber instance.
    """
    subscription_id: str
    event_type: str
    subscriber: Subscriber
