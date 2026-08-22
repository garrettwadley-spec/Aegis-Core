"""Canonical market-data ingestion bus."""
from __future__ import annotations

from aegis.eventbus import Event, EventBus, Subscriber, Subscription

from .models import MarketData, RawMarketData, normalize_market_data


MARKET_DATA_RECEIVED = "MarketDataReceived"


class MarketDataBus:
    """Validate, normalize, and publish canonical market observations."""

    def __init__(self) -> None:
        self._event_bus = EventBus()

    def ingest(self, raw_market_data: RawMarketData) -> MarketData:
        market_data = normalize_market_data(raw_market_data)
        self._event_bus.publish(Event.create(MARKET_DATA_RECEIVED, market_data))
        self._event_bus.dispatch()
        return market_data

    def subscribe(self, subscriber: Subscriber) -> Subscription:
        return self._event_bus.subscribe(MARKET_DATA_RECEIVED, subscriber)
