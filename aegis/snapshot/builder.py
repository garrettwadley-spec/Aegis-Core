"""Build canonical snapshots from MarketDataReceived events."""
from __future__ import annotations

from aegis.clock import system_clock
from aegis.eventbus import Event, EventBus, Subscriber, Subscription
from aegis.marketdata import MarketData

from .models import MarketSnapshot


MARKET_SNAPSHOT_CREATED = "MarketSnapshotCreated"


class MarketSnapshotBuilder(Subscriber):
    """Maintain latest-per-symbol state and materialize immutable snapshots."""

    def __init__(self) -> None:
        self._latest: dict[str, tuple[int, MarketData]] = {}
        self._event_bus = EventBus()

    def receive(self, event: Event) -> None:
        sequence = event.sequence_number
        if sequence is None:
            raise ValueError("MarketDataReceived event requires a sequence number")

        market_data = event.payload
        current = self._latest.get(market_data.symbol)
        if current is None or sequence > current[0]:
            self._latest[market_data.symbol] = (sequence, market_data)

    def build(self) -> MarketSnapshot:
        if not self._latest:
            raise ValueError("cannot build a market snapshot without market data")

        ordered = sorted(self._latest.values(), key=lambda item: item[0])
        as_of = system_clock.now()
        snapshot = MarketSnapshot(
            as_of=as_of,
            market_data=tuple(item[1] for item in ordered),
            source_event_sequences=tuple(item[0] for item in ordered),
            created_at=as_of,
        )
        self._event_bus.publish(Event.create(MARKET_SNAPSHOT_CREATED, snapshot))
        self._event_bus.dispatch()
        return snapshot

    def subscribe(self, subscriber: Subscriber) -> Subscription:
        return self._event_bus.subscribe(MARKET_SNAPSHOT_CREATED, subscriber)
