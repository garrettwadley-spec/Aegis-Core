"""Run the deterministic end-to-end Market Snapshot launch demo."""
from __future__ import annotations

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource
from aegis.snapshot import MarketSnapshotBuilder


class MarketDataPrinter(Subscriber):
    def receive(self, event: Event) -> None:
        market_data = event.payload
        print(
            f"[{event.sequence_number}] {event.event_type} "
            f"{market_data.symbol} last={market_data.last:.2f}"
        )


class SnapshotPrinter(Subscriber):
    def receive(self, event: Event) -> None:
        snapshot = event.payload
        print(
            f"[{event.sequence_number}] {event.event_type} "
            f"as_of={snapshot.as_of.isoformat()} symbols={len(snapshot.market_data)}"
        )
        for market_data, sequence in zip(
            snapshot.market_data,
            snapshot.source_event_sequences,
        ):
            print(
                f"  {market_data.symbol} last={market_data.last:.2f} "
                f"source_sequence={sequence}"
            )


def observation(symbol: str, last: float, source_timestamp: str) -> RawMarketData:
    return RawMarketData(
        symbol=symbol,
        exchange="XNAS" if symbol != "SPY" else "ARCX",
        bid=last - 0.02,
        ask=last + 0.02,
        last=last,
        volume=1_000,
        source="replay",
        source_timestamp=source_timestamp,
    )


def main() -> None:
    observations = [
        observation("SPY", 645.12, "2026-01-02T14:30:00Z"),
        observation("NVDA", 182.44, "2026-01-02T14:30:01Z"),
        observation("AAPL", 231.08, "2026-01-02T14:30:02Z"),
        observation("SPY", 645.36, "2026-01-02T14:30:03Z"),
    ]

    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2026-01-02T14:30:00+00:00",
        replay_step_seconds=1.0,
        sequence_start=1,
    )
    try:
        market_data_bus = MarketDataBus()
        snapshot_builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(MarketDataPrinter())
        market_data_bus.subscribe(snapshot_builder)
        snapshot_builder.subscribe(SnapshotPrinter())

        list(ReplaySource(observations).run(market_data_bus))
        snapshot_builder.build()
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
