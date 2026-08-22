"""Focused tests for snapshot-to-strategy ignition."""
from __future__ import annotations

from typing import Any
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource
from aegis.snapshot import MarketSnapshot, MarketSnapshotBuilder
from aegis.strategies import (
    MarketSignal,
    OpeningRangeStrategy,
    SnapshotStrategyBridge,
)
from aegis.strategies.strategy_base import StrategyBase


def observation(symbol: str = "SPY", last: float = 645.12) -> RawMarketData:
    return RawMarketData(
        symbol=symbol,
        exchange="ARCX",
        bid=last - 0.02,
        ask=last + 0.02,
        last=last,
        volume=1_000,
        source="replay",
        source_timestamp="2026-01-02T14:30:00Z",
    )


def opening_range_configuration() -> dict[str, dict[str, Any]]:
    return {
        "SPY": {
            "relative_volume": 5.0,
            "price_change_pct": 10.0,
            "rsi": 32.0,
            "macd_cross": True,
        }
    }


class RecordingStrategy(StrategyBase):
    name = "Recording Strategy"

    def __init__(self) -> None:
        self.inputs: list[dict] = []

    def evaluate(self, market_data: dict) -> MarketSignal | None:
        self.inputs.append(market_data)
        return MarketSignal(
            symbol=market_data["symbol"],
            action="BUY",
            confidence=0.75,
            strategy=self.name,
        )


class TestSnapshotStrategyBridge(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def pipeline(
        self,
        bridge: SnapshotStrategyBridge,
    ) -> tuple[MarketDataBus, MarketSnapshotBuilder]:
        market_data_bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(builder)
        builder.subscribe(bridge)
        return market_data_bus, builder

    def test_snapshot_event_feeds_existing_strategy_bridge(self):
        bridge = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_configuration(),
        )
        market_data_bus, builder = self.pipeline(bridge)

        market_data_bus.ingest(observation())
        builder.build()

        self.assertEqual(bridge.last_evaluated_symbols, ("SPY",))
        self.assertEqual(bridge.last_signals[0].action, "BUY")

    def test_bridge_uses_latest_state_and_excludes_replaced_observation(self):
        strategy = RecordingStrategy()
        bridge = SnapshotStrategyBridge(
            strategy,
            {"SPY": {"symbol": "OTHER", "last": 1.0}},
        )
        market_data_bus, builder = self.pipeline(bridge)
        market_data_bus.ingest(observation("SPY", 645.12))
        market_data_bus.ingest(observation("SPY", 645.36))

        builder.build()

        self.assertEqual(len(strategy.inputs), 1)
        self.assertEqual(strategy.inputs[0]["symbol"], "SPY")
        self.assertEqual(strategy.inputs[0]["last"], 645.36)
        self.assertEqual(strategy.inputs[0]["source_event_sequence"], 2)

    def test_identical_snapshot_and_configuration_are_deterministic(self):
        market_data_bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(builder)
        market_data_bus.ingest(observation())
        snapshot = builder.build()
        bridge = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_configuration(),
        )

        first = bridge.evaluate(snapshot)
        second = bridge.evaluate(snapshot)

        self.assertEqual(first, second)

    def test_strategy_receives_transient_dict_not_raw_market_data(self):
        strategy = RecordingStrategy()
        bridge = SnapshotStrategyBridge(strategy, {"SPY": {}})
        market_data_bus, builder = self.pipeline(bridge)
        market_data_bus.ingest(observation())

        builder.build()

        self.assertIsInstance(strategy.inputs[0], dict)
        self.assertNotIsInstance(strategy.inputs[0], RawMarketData)

    def test_existing_opening_range_behavior_is_preserved(self):
        signal = OpeningRangeStrategy().evaluate(
            {
                "symbol": "SPY",
                "relative_volume": 5.0,
                "price_change_pct": 10.0,
                "rsi": 32.0,
                "macd_cross": True,
            }
        )

        self.assertEqual(
            signal,
            MarketSignal(
                symbol="SPY",
                action="BUY",
                confidence=0.92,
                strategy="Opening Range Breakout",
                quantity=1,
            ),
        )

    def test_replay_to_snapshot_to_strategy_runs_end_to_end(self):
        bridge = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_configuration(),
        )
        market_data_bus, builder = self.pipeline(bridge)
        observations = [
            observation("SPY", 645.12),
            observation("NVDA", 182.44),
            observation("AAPL", 231.08),
            observation("SPY", 645.36),
        ]

        replayed = list(ReplaySource(observations).run(market_data_bus))
        snapshot = builder.build()

        self.assertEqual(len(replayed), 4)
        self.assertIsInstance(snapshot, MarketSnapshot)
        self.assertEqual(bridge.last_evaluated_symbols, ("SPY",))
        self.assertEqual(bridge.last_signals[0].symbol, "SPY")
        self.assertEqual(bridge.last_signals[0].action, "BUY")


if __name__ == "__main__":
    unittest.main()
