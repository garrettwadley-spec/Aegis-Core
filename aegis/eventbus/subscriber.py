"""Subscriber abstraction for the Event Bus."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from .event import Event

class Subscriber(ABC):
    """Abstract Subscriber interface.

    Implementations must provide a synchronous receive method. The EventBus
    will call receive(event) during dispatch in deterministic order.
    """

    @abstractmethod
    def receive(self, event: Event) -> Any:
        """Handle an incoming Event.

        The return value is ignored by the EventBus, but implementers may
        return diagnostics for testing.
        """
        raise NotImplementedError
