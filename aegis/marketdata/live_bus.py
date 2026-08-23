"""EventBus boundary for normalized live trades and quotes."""
from __future__ import annotations

from aegis.eventbus import Event, EventBus, Subscriber, Subscription

from .live_models import LiveQuote, LiveTrade


LIVE_TRADE_RECEIVED = "LiveTradeReceived"
LIVE_QUOTE_RECEIVED = "LiveQuoteReceived"


class LiveMarketDataBus:
    """Publish only normalized provider-neutral live observations."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus or EventBus()

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def ingest(self, observation: LiveTrade | LiveQuote) -> LiveTrade | LiveQuote:
        if isinstance(observation, LiveTrade):
            event_type = LIVE_TRADE_RECEIVED
        elif isinstance(observation, LiveQuote):
            event_type = LIVE_QUOTE_RECEIVED
        else:
            raise TypeError("live market bus accepts normalized LiveTrade or LiveQuote only")
        self._event_bus.publish(
            Event.create(
                event_type,
                observation,
                trace_id=observation.trace_id,
                correlation_id=observation.correlation_id,
            )
        )
        self._event_bus.dispatch()
        return observation

    def subscribe(self, event_type: str, subscriber: Subscriber) -> Subscription:
        if event_type not in (LIVE_TRADE_RECEIVED, LIVE_QUOTE_RECEIVED):
            raise ValueError("unsupported live market event type")
        return self._event_bus.subscribe(event_type, subscriber)
