"""Focused LAUNCH-011 Massive stream tests."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
import unittest
from unittest.mock import patch

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import EventBus
from aegis.marketdata import (
    DEFAULT_MASSIVE_WS_URL,
    LiveMarketDataBus,
    LiveQuote,
    LiveTrade,
    MassiveStockStreamAdapter,
    OpeningRangeBuilder,
    ThirtySecondBar,
    ThirtySecondBarBuilder,
    massive_credential_present,
    normalize_massive_message,
    parse_massive_sip_timestamp,
)
from scripts.run_massive_fixture_demo import main as fixture_main


UTC = timezone.utc


def milliseconds(timestamp: datetime) -> int:
    return int(timestamp.timestamp() * 1000)


SOURCE_TIME = datetime(2026, 1, 2, 14, 30, 5, tzinfo=UTC)


def trade_message(**overrides: object) -> dict[str, object]:
    message: dict[str, object] = {
        "ev": "T",
        "sym": "spy",
        "p": 500.10,
        "s": 100,
        "x": 4,
        "i": "M1",
        "c": [12, 37],
        "t": milliseconds(SOURCE_TIME),
        "pt": milliseconds(SOURCE_TIME) - 1,
        "q": 7001,
        "z": 3,
    }
    message.update(overrides)
    return message


def quote_message(**overrides: object) -> dict[str, object]:
    message: dict[str, object] = {
        "ev": "Q",
        "sym": "spy",
        "bp": 500.08,
        "bs": 20,
        "bx": 11,
        "ap": 500.12,
        "as": 25,
        "ax": 12,
        "c": 1,
        "i": [2, 7],
        "t": milliseconds(SOURCE_TIME),
        "q": 7002,
        "z": 3,
    }
    message.update(overrides)
    return message


class MassiveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:40:00+00:00",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def adapter(self, sink=None, **overrides):
        values = {
            "symbols": ("SPY",),
            "observation_sink": (lambda item: None) if sink is None else sink,
            "api_key": "test-key",
        }
        values.update(overrides)
        return MassiveStockStreamAdapter(**values)


class TestMassiveNormalization(MassiveTestCase):
    def test_authentication_status_never_enters_market_logic(self):
        delivered: list[object] = []
        adapter = self.adapter(delivered.append)
        result = adapter.handle_message(
            {"ev": "status", "status": "auth_success", "message": "authenticated"}
        )
        self.assertIsNone(result)
        self.assertEqual(delivered, [])
        self.assertTrue(adapter.status.authenticated)
        self.assertEqual(adapter.status.control_messages_received, 1)

    def test_subscription_status_never_enters_market_logic(self):
        delivered: list[object] = []
        adapter = self.adapter(delivered.append)
        adapter.handle_message(
            {
                "ev": "status",
                "status": "success",
                "message": "subscribed to: T.SPY,Q.SPY",
            }
        )
        self.assertEqual(delivered, [])
        self.assertTrue(adapter.status.subscribed)
        self.assertEqual(adapter.status.accepted_subscriptions, ("T.SPY", "Q.SPY"))

    def test_split_subscription_acknowledgements_accumulate(self):
        adapter = self.adapter()
        adapter.handle_message(
            {"ev": "status", "status": "success", "message": "subscribed to: T.SPY"}
        )
        self.assertFalse(adapter.status.subscribed)
        adapter.handle_message(
            {"ev": "status", "status": "success", "message": "subscribed to: Q.SPY"}
        )
        self.assertTrue(adapter.status.subscribed)
        self.assertEqual(adapter.status.accepted_subscriptions, ("T.SPY", "Q.SPY"))

    def test_trade_normalizes_into_existing_live_trade(self):
        trade = normalize_massive_message(
            trade_message(),
            received_at=SOURCE_TIME + timedelta(milliseconds=10),
        )
        self.assertIsInstance(trade, LiveTrade)
        self.assertEqual((trade.symbol, trade.price, trade.size), ("SPY", 500.10, 100.0))
        self.assertEqual((trade.exchange, trade.trade_id, trade.source), ("4", "M1", "massive"))

    def test_quote_normalizes_into_existing_live_quote(self):
        quote = normalize_massive_message(
            quote_message(),
            received_at=SOURCE_TIME + timedelta(milliseconds=10),
        )
        self.assertIsInstance(quote, LiveQuote)
        self.assertEqual((quote.bid_price, quote.ask_price), (500.08, 500.12))
        self.assertEqual((quote.bid_exchange, quote.ask_exchange), ("11", "12"))

    def test_sip_timestamp_converts_from_unix_milliseconds(self):
        self.assertEqual(parse_massive_sip_timestamp(milliseconds(SOURCE_TIME)), SOURCE_TIME)
        trade = normalize_massive_message(trade_message(), received_at=SOURCE_TIME)
        self.assertEqual(trade.source_timestamp, SOURCE_TIME)  # type: ignore[union-attr]

    def test_provider_sequence_and_trade_provenance_are_immutable(self):
        trade = normalize_massive_message(trade_message(), received_at=SOURCE_TIME)
        self.assertEqual(trade.metadata["provider_sequence"], 7001)  # type: ignore[union-attr]
        self.assertEqual(trade.metadata["participant_timestamp"], milliseconds(SOURCE_TIME) - 1)  # type: ignore[union-attr]
        self.assertEqual(trade.metadata["tape"], 3)  # type: ignore[union-attr]
        self.assertEqual(trade.conditions, ("12", "37"))  # type: ignore[union-attr]
        with self.assertRaises(TypeError):
            trade.metadata["provider_sequence"] = 1  # type: ignore[index,union-attr]

    def test_quote_condition_indicators_sequence_and_tape_are_preserved(self):
        quote = normalize_massive_message(quote_message(), received_at=SOURCE_TIME)
        self.assertEqual(quote.metadata["provider_sequence"], 7002)  # type: ignore[union-attr]
        self.assertEqual(quote.metadata["condition"], 1)  # type: ignore[union-attr]
        self.assertEqual(quote.metadata["indicators"], ("2", "7"))  # type: ignore[union-attr]
        self.assertEqual(quote.metadata["tape"], 3)  # type: ignore[union-attr]

    def test_invalid_trade_is_rejected_explicitly(self):
        for overrides in (
            {"sym": ""},
            {"p": 0},
            {"p": float("nan")},
            {"s": -1},
            {"t": "invalid"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    normalize_massive_message(
                        trade_message(**overrides),
                        received_at=SOURCE_TIME,
                    )

    def test_invalid_or_crossed_quote_is_rejected_explicitly(self):
        for overrides in (
            {"sym": ""},
            {"bp": float("inf")},
            {"bs": -1},
            {"bp": 500.13, "ap": 500.12},
            {"t": None},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    normalize_massive_message(
                        quote_message(**overrides),
                        received_at=SOURCE_TIME,
                    )

    def test_credentials_are_absent_from_status_repr_and_output(self):
        adapter = self.adapter(api_key="SENSITIVE_MASSIVE_KEY")
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            adapter.handle_message(
                {"ev": "status", "status": "auth_success", "message": "authenticated"}
            )
        rendered = repr(adapter) + repr(adapter.status) + output.getvalue()
        self.assertNotIn("SENSITIVE_MASSIVE_KEY", rendered)
        self.assertTrue(massive_credential_present({"MASSIVE_API_KEY": "present"}))
        self.assertFalse(massive_credential_present({}))

    def test_bounded_watchlist_and_no_wildcards_are_enforced(self):
        with self.assertRaises(ValueError):
            self.adapter(symbols=())
        with self.assertRaises(ValueError):
            self.adapter(symbols=tuple(f"S{index}" for index in range(21)))
        with self.assertRaises(ValueError):
            self.adapter(symbols=("*",))
        with self.assertRaises(ValueError):
            self.adapter(symbols=("SPY", "Q.*"))
        adapter = self.adapter(symbols=("spy", "qqq"))
        self.assertEqual(
            adapter.status.requested_subscriptions,
            ("T.SPY", "T.QQQ", "Q.SPY", "Q.QQQ"),
        )


class TestMassivePipelineAndMetrics(MassiveTestCase):
    def test_massive_observations_feed_existing_bar_and_quote_state(self):
        event_bus = EventBus()
        live_bus = LiveMarketDataBus(event_bus)
        builder = ThirtySecondBarBuilder(event_bus)
        OpeningRangeBuilder(event_bus)
        delivered: list[LiveTrade | LiveQuote] = []
        adapter = self.adapter(
            lambda item: (delivered.append(item), live_bus.ingest(item))
        )
        interval_start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
        adapter.handle_message(
            quote_message(t=milliseconds(interval_start + timedelta(seconds=1)))
        )
        adapter.handle_message(
            trade_message(t=milliseconds(interval_start + timedelta(seconds=5)), p=500.10)
        )
        adapter.handle_message(
            trade_message(
                t=milliseconds(interval_start + timedelta(seconds=20)),
                p=500.25,
                i="M2",
                q=7003,
            )
        )
        builder.advance("SPY", interval_start + timedelta(seconds=30))
        event_bus.dispatch()
        bar = builder.bars[0]
        self.assertIsInstance(bar, ThirtySecondBar)
        self.assertEqual((bar.open, bar.close), (500.10, 500.25))
        self.assertEqual((bar.latest_bid, bar.latest_ask), (500.08, 500.12))
        self.assertTrue(all(isinstance(item, (LiveTrade, LiveQuote)) for item in delivered))
        self.assertTrue(all(item.source == "massive" for item in delivered))

    def test_latency_statistics_and_invalid_samples_are_exact(self):
        adapter = self.adapter()
        receive_times = [
            SOURCE_TIME + timedelta(milliseconds=10),
            SOURCE_TIME + timedelta(milliseconds=20),
            SOURCE_TIME + timedelta(milliseconds=30),
            SOURCE_TIME + timedelta(milliseconds=40),
            SOURCE_TIME - timedelta(milliseconds=5),
        ]
        with patch.object(system_clock, "now", side_effect=receive_times):
            for index in range(5):
                adapter.handle_message(trade_message(i=f"M{index}", q=8000 + index))
        stats = adapter.latency_statistics
        self.assertEqual(stats.count, 4)
        self.assertAlmostEqual(stats.minimum_ms, 10.0)
        self.assertAlmostEqual(stats.mean_ms, 25.0)
        self.assertAlmostEqual(stats.p50_ms, 20.0)
        self.assertAlmostEqual(stats.p95_ms, 40.0)
        self.assertAlmostEqual(stats.maximum_ms, 40.0)
        self.assertEqual(stats.invalid_samples, 1)

    def test_capacity_metrics_record_zero_drops_and_malformed_messages(self):
        adapter = self.adapter()
        adapter.handle_message(trade_message())
        adapter.handle_message({"ev": "T", "sym": "SPY", "p": "bad"})
        capacity = adapter.capacity_statistics
        self.assertEqual(capacity.handler_count, 2)
        self.assertGreaterEqual(capacity.peak_messages_per_second, 1)
        self.assertEqual(capacity.queue_depth, 0)
        self.assertEqual(capacity.dropped_messages, 0)
        self.assertEqual(capacity.malformed_messages, 1)

    def test_delivery_failure_is_counted_as_a_dropped_message(self):
        def fail_delivery(item):
            raise RuntimeError("fixture sink failure")

        adapter = self.adapter(fail_delivery)
        with self.assertRaises(RuntimeError):
            adapter.handle_message(trade_message())
        self.assertEqual(adapter.status.dropped_messages, 1)

    def test_invalid_raw_payload_is_counted_as_received_and_malformed(self):
        adapter = self.adapter()
        self.assertEqual(adapter.handle_payload("not-json"), ())
        self.assertEqual(adapter.status.messages_received, 1)
        self.assertEqual(adapter.status.malformed_messages, 1)
        self.assertEqual(adapter.capacity_statistics.handler_count, 1)

    def test_offline_fixture_demo_succeeds(self):
        output = StringIO()
        with redirect_stdout(output):
            fixture_main()
        rendered = output.getvalue()
        self.assertIn("Authenticated: True", rendered)
        self.assertIn("Subscribed: True", rendered)
        self.assertIn("Completed: 12", rendered)
        self.assertIn("Complete: True", rendered)
        self.assertIn("Provider-neutral path: True", rendered)
        self.assertIn("Dropped: 0", rendered)


class _FailingConnect:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise OSError("fixture connection failure")


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.closed = False
        self._responses = [
            json.dumps(
                [{"ev": "status", "status": "auth_success", "message": "authenticated"}]
            ),
            json.dumps(
                [{"ev": "status", "status": "success", "message": "subscribed to: T.SPY,Q.SPY"}]
            ),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def recv(self) -> str:
        if self._responses:
            return self._responses.pop(0)
        await __import__("asyncio").sleep(1)
        return "[]"


class _FakeConnect:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self.websocket = websocket
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.websocket


class TestMassiveConnectionLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:40:00+00:00",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    async def asyncTearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    async def test_bounded_reconnect_terminates(self):
        connector = _FailingConnect()
        adapter = MassiveStockStreamAdapter(
            symbols=("SPY",),
            observation_sink=lambda item: None,
            api_key="test-key",
            max_attempts=2,
            reconnect_delay_seconds=0,
            connect_factory=connector,
        )
        observations = await adapter.run(max_seconds=0.1)
        self.assertEqual(observations, ())
        self.assertEqual(connector.calls, 2)
        self.assertEqual(adapter.status.reconnect_count, 1)
        self.assertFalse(adapter.status.connected)

    async def test_clean_shutdown_after_bounded_stream(self):
        websocket = _FakeWebSocket()
        connector = _FakeConnect(websocket)
        adapter = MassiveStockStreamAdapter(
            symbols=("SPY",),
            observation_sink=lambda item: None,
            api_key="test-key",
            max_attempts=1,
            reconnect_delay_seconds=0,
            connect_factory=connector,
        )
        observations = await adapter.run(max_seconds=0.02)
        self.assertEqual(observations, ())
        self.assertTrue(adapter.status.authenticated)
        self.assertTrue(adapter.status.subscribed)
        self.assertTrue(websocket.closed)
        self.assertFalse(adapter.status.connected)
        self.assertEqual(websocket.sent[0]["action"], "auth")
        self.assertEqual(websocket.sent[1]["params"], "T.SPY,Q.SPY")


if __name__ == "__main__":
    unittest.main()
