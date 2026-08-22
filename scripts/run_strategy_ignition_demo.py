"""Run the deterministic snapshot-to-strategy ignition demo."""
from __future__ import annotations

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


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
            f"symbols={len(snapshot.market_data)} as_of={snapshot.as_of.isoformat()}"
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
    strategy = OpeningRangeStrategy()
    bridge = SnapshotStrategyBridge(
        strategy,
        {
            "SPY": {
                "relative_volume": 5.0,
                "price_change_pct": 10.0,
                "rsi": 32.0,
                "macd_cross": True,
            }
        },
    )

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
        snapshot_builder.subscribe(bridge)

        list(ReplaySource(observations).run(market_data_bus))
        snapshot_builder.build()

        print(f"Strategy: {bridge.strategy_name}")
        print(f"Evaluated: {', '.join(bridge.last_evaluated_symbols)}")
        if not bridge.last_signals:
            print("Result: NO_ACTION")
        else:
            for signal in bridge.last_signals:
                print(f"Result: {signal.action} {signal.symbol}")
                print(f"Confidence: {signal.confidence:.2f}")
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
