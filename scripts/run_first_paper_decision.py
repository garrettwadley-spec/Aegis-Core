"""Run Aegis's first complete autonomous offline paper decision."""
from __future__ import annotations

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.execution import DecisionJournal, PaperDecisionService
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
    strategy_bridge = SnapshotStrategyBridge(
        OpeningRangeStrategy(),
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
        snapshot_builder.subscribe(strategy_bridge)

        list(ReplaySource(observations).run(market_data_bus))
        snapshot = snapshot_builder.build()
        signal = strategy_bridge.last_signals[0]
        outcome = PaperDecisionService(DecisionJournal()).execute(signal, snapshot)

        response = outcome.execution_result.broker_response
        print(f"Strategy: {signal.strategy}")
        print(
            f"Signal: {signal.action} {signal.symbol} "
            f"confidence={signal.confidence:.2f}"
        )
        print(
            f"TradeRequest: {outcome.request.side.value} "
            f"{outcome.request.quantity} {outcome.request.symbol} "
            f"mode={outcome.request.mode.value.upper()}"
        )
        print(f"Execution: {outcome.execution_result.status.value.upper()}")
        print(f"Paper Order: {response['paper_order_id']}")
        print(
            f"Fill: {response['fill_quantity']} @ "
            f"{response['fill_price']:.2f}"
        )
        print(f"Decision Recorded: {outcome.record_path.as_posix()}")
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
