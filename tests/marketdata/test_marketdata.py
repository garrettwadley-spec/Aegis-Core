"""Focused tests for canonical market-data ingestion."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.marketdata import (
    MARKET_DATA_RECEIVED,
    MarketData,
    MarketDataBus,
    RawMarketData,
    ReplaySource,
    normalize_market_data,
)


def raw_market_data(**overrides) -> RawMarketData:
    values = {
        "symbol": "SPY",
        "exchange": "ARCX",
        "bid": 645.10,
        "ask": 645.14,
        "last": 645.12,
        "volume": 1_000,
        "source": "replay",
        "source_timestamp": "2026-01-02T09:30:00-05:00",
    }
    values.update(overrides)
    return RawMarketData(**values)


class RecordingSubscriber(Subscriber):
    def __init__(self) -> None:
        self.events: list[Event] = []

    def receive(self, event: Event) -> None:
        self.events.append(event)


class TestMarketDataModel(unittest.TestCase):
    def test_valid_observation_becomes_immutable_market_data(self):
        market_data = normalize_market_data(raw_market_data(symbol=" spy "))

        self.assertIsInstance(market_data, MarketData)
        self.assertEqual(market_data.symbol, "SPY")
        with self.assertRaises(FrozenInstanceError):
            market_data.last = 1.0  # type: ignore[misc]

    def test_empty_symbol_rejected(self):
        with self.assertRaises(ValueError):
            normalize_market_data(raw_market_data(symbol="  "))

    def test_missing_source_rejected(self):
        with self.assertRaises(ValueError):
            normalize_market_data(raw_market_data(source=""))

    def test_negative_volume_rejected(self):
        with self.assertRaises(ValueError):
            normalize_market_data(raw_market_data(volume=-1))

    def test_nan_price_rejected(self):
        with self.assertRaises(ValueError):
            normalize_market_data(raw_market_data(last=float("nan")))

    def test_infinite_price_rejected(self):
        with self.assertRaises(ValueError):
            normalize_market_data(raw_market_data(ask=float("inf")))

    def test_malformed_source_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            normalize_market_data(raw_market_data(source_timestamp="not-a-time"))

    def test_source_timestamp_normalizes_to_utc(self):
        market_data = normalize_market_data(raw_market_data())

        self.assertEqual(
            market_data.source_timestamp,
            datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc),
        )

    def test_received_at_originates_from_clock(self):
        expected = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
        with patch.object(system_clock, "now", return_value=expected) as clock_now:
            market_data = normalize_market_data(raw_market_data())

        self.assertEqual(market_data.received_at, expected)
        clock_now.assert_called_once_with()


class TestMarketDataBus(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=100,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_ingest_publishes_exact_canonical_payload(self):
        market_data_bus = MarketDataBus()
        subscriber = RecordingSubscriber()
        market_data_bus.subscribe(subscriber)

        market_data = market_data_bus.ingest(raw_market_data())

        self.assertEqual(len(subscriber.events), 1)
        self.assertEqual(subscriber.events[0].event_type, MARKET_DATA_RECEIVED)
        self.assertIs(subscriber.events[0].payload, market_data)

    def test_event_sequence_is_clock_owned(self):
        market_data_bus = MarketDataBus()
        subscriber = RecordingSubscriber()
        market_data_bus.subscribe(subscriber)

        market_data_bus.ingest(raw_market_data())
        next_clock_sequence = system_clock.sequence()

        self.assertEqual(subscriber.events[0].sequence_number, 100)
        self.assertEqual(next_clock_sequence, 101)

    def test_three_replay_observations_preserve_order(self):
        market_data_bus = MarketDataBus()
        subscriber = RecordingSubscriber()
        market_data_bus.subscribe(subscriber)
        observations = [
            raw_market_data(symbol="SPY"),
            raw_market_data(symbol="NVDA"),
            raw_market_data(symbol="AAPL"),
        ]

        market_data = list(ReplaySource(observations).run(market_data_bus))

        self.assertEqual([item.symbol for item in market_data], ["SPY", "NVDA", "AAPL"])
        self.assertEqual(
            [event.payload.symbol for event in subscriber.events],
            ["SPY", "NVDA", "AAPL"],
        )
        self.assertEqual(
            [event.sequence_number for event in subscriber.events],
            [100, 101, 102],
        )

    def test_invalid_data_publishes_no_event(self):
        market_data_bus = MarketDataBus()
        subscriber = RecordingSubscriber()
        market_data_bus.subscribe(subscriber)

        with self.assertRaises(ValueError):
            market_data_bus.ingest(raw_market_data(volume=-1))

        self.assertEqual(subscriber.events, [])


if __name__ == "__main__":
    unittest.main()
