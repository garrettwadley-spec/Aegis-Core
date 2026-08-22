"""Focused tests for canonical market snapshots."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource
from aegis.snapshot import (
    MARKET_SNAPSHOT_CREATED,
    MarketSnapshot,
    MarketSnapshotBuilder,
)


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


class RecordingSubscriber(Subscriber):
    def __init__(self) -> None:
        self.events: list[Event] = []

    def receive(self, event: Event) -> None:
        self.events.append(event)


class TestMarketSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def pipeline(self) -> tuple[MarketDataBus, MarketSnapshotBuilder]:
        market_data_bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(builder)
        return market_data_bus, builder

    def test_snapshot_is_immutable(self):
        market_data_bus, builder = self.pipeline()
        market_data_bus.ingest(observation())

        snapshot = builder.build()

        self.assertIsInstance(snapshot, MarketSnapshot)
        self.assertIsInstance(snapshot.market_data, tuple)
        self.assertIsInstance(snapshot.source_event_sequences, tuple)
        with self.assertRaises(FrozenInstanceError):
            snapshot.as_of = datetime(  # type: ignore[misc]
                2026,
                1,
                2,
                tzinfo=timezone.utc,
            )

    def test_builder_receives_market_data_events(self):
        market_data_bus, builder = self.pipeline()

        canonical = market_data_bus.ingest(observation())
        snapshot = builder.build()

        self.assertIs(snapshot.market_data[0], canonical)

    def test_three_symbols_produce_three_symbol_snapshot(self):
        market_data_bus, builder = self.pipeline()
        for symbol in ("SPY", "NVDA", "AAPL"):
            market_data_bus.ingest(observation(symbol))

        snapshot = builder.build()

        self.assertEqual(len(snapshot.market_data), 3)

    def test_newer_observation_replaces_same_symbol(self):
        market_data_bus, builder = self.pipeline()
        market_data_bus.ingest(observation("SPY", 645.12))
        newest = market_data_bus.ingest(observation("SPY", 645.36))

        snapshot = builder.build()

        self.assertEqual(len(snapshot.market_data), 1)
        self.assertIs(snapshot.market_data[0], newest)

    def test_source_event_sequence_provenance_is_preserved(self):
        market_data_bus, builder = self.pipeline()
        market_data_bus.ingest(observation("SPY"))
        market_data_bus.ingest(observation("NVDA"))

        snapshot = builder.build()

        self.assertEqual(snapshot.source_event_sequences, (1, 2))

    def test_snapshot_order_is_deterministic_by_current_source_sequence(self):
        market_data_bus, builder = self.pipeline()
        market_data_bus.ingest(observation("SPY", 645.12))
        market_data_bus.ingest(observation("AAPL", 231.08))
        market_data_bus.ingest(observation("NVDA", 182.44))
        market_data_bus.ingest(observation("SPY", 645.36))

        snapshot = builder.build()

        self.assertEqual(
            [market_data.symbol for market_data in snapshot.market_data],
            ["AAPL", "NVDA", "SPY"],
        )
        self.assertEqual(snapshot.source_event_sequences, (2, 3, 4))

    def test_snapshot_as_of_originates_from_clock(self):
        market_data_bus, builder = self.pipeline()
        market_data_bus.ingest(observation())
        expected = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)

        with patch.object(system_clock, "now", return_value=expected) as clock_now:
            snapshot = builder.build()

        self.assertEqual(snapshot.as_of, expected)
        self.assertEqual(clock_now.call_count, 2)

    def test_snapshot_created_publishes_exact_payload(self):
        market_data_bus, builder = self.pipeline()
        subscriber = RecordingSubscriber()
        builder.subscribe(subscriber)
        market_data_bus.ingest(observation())

        snapshot = builder.build()

        self.assertEqual(len(subscriber.events), 1)
        self.assertEqual(subscriber.events[0].event_type, MARKET_SNAPSHOT_CREATED)
        self.assertIs(subscriber.events[0].payload, snapshot)

    def test_empty_builder_fails_explicitly(self):
        builder = MarketSnapshotBuilder()

        with self.assertRaisesRegex(ValueError, "without market data"):
            builder.build()

    def test_replay_to_snapshot_pipeline_end_to_end(self):
        market_data_bus, builder = self.pipeline()
        observations = [
            observation("SPY", 645.12),
            observation("NVDA", 182.44),
            observation("AAPL", 231.08),
            observation("SPY", 645.36),
        ]

        replayed = list(ReplaySource(observations).run(market_data_bus))
        snapshot = builder.build()

        self.assertEqual(len(replayed), 4)
        self.assertEqual(
            {item.symbol: item.last for item in snapshot.market_data},
            {"SPY": 645.36, "NVDA": 182.44, "AAPL": 231.08},
        )
        self.assertEqual(snapshot.source_event_sequences, (2, 3, 4))


if __name__ == "__main__":
    unittest.main()
