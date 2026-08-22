"""Focused tests for the first autonomous offline paper decision."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from aegis.clock import ClockMode, system_clock
from aegis.execution import (
    DecisionJournal,
    ExecutionEngine,
    ExecutionMode,
    ExecutionResult,
    ExecutionStatus,
    INPUT_ORIGIN,
    LaunchSafetyGate,
    OfflinePaperBroker,
    OrderRouter,
    OrderSide,
    PaperDecisionService,
    SignalToTradeBridge,
    TradeRequest,
)
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import (
    MarketSignal,
    OpeningRangeStrategy,
    SnapshotStrategyBridge,
)


def observation(symbol: str = "SPY", last: float = 645.36) -> RawMarketData:
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


def actionable_signal(action: str = "BUY") -> MarketSignal:
    return MarketSignal(
        symbol="SPY",
        action=action,
        confidence=0.92,
        strategy="Opening Range Breakout",
        quantity=1,
    )


class TestOfflinePaperDecision(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def snapshot(self, last: float = 645.36):
        market_data_bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(builder)
        market_data_bus.ingest(observation(last=last))
        return builder.build()

    def test_actionable_signal_creates_one_share_paper_request(self):
        request = SignalToTradeBridge().create_request(actionable_signal())
        sell_request = SignalToTradeBridge().create_request(
            actionable_signal("SELL")
        )

        self.assertIsNotNone(request)
        self.assertEqual(request.mode, ExecutionMode.PAPER)
        self.assertEqual(request.side, OrderSide.BUY)
        self.assertEqual(request.quantity, 1)
        self.assertEqual(sell_request.mode, ExecutionMode.PAPER)
        self.assertEqual(sell_request.side, OrderSide.SELL)

    def test_non_actionable_signal_creates_no_request(self):
        bridge = SignalToTradeBridge()

        self.assertIsNone(bridge.create_request(None))
        self.assertIsNone(bridge.create_request(actionable_signal("HOLD")))

    def test_live_mode_cannot_pass_launch_safety_gate(self):
        request = TradeRequest(
            symbol="SPY",
            quantity=1,
            side=OrderSide.BUY,
            strategy="Opening Range Breakout",
            confidence=0.92,
            mode=ExecutionMode.LIVE,
        )

        with self.assertRaisesRegex(ValueError, "must be PAPER"):
            LaunchSafetyGate.validate(request, 645.36, actionable_signal())

    def test_invalid_quantity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            SignalToTradeBridge(quantity=0)

    def test_invalid_price_is_rejected_and_recorded(self):
        with TemporaryDirectory() as directory:
            journal = DecisionJournal(Path(directory) / "decisions.jsonl")
            outcome = PaperDecisionService(journal).execute(
                actionable_signal(),
                self.snapshot(last=-1.0),
            )

            self.assertEqual(outcome.execution_result.status, ExecutionStatus.REJECTED)
            self.assertIsNone(outcome.record["paper_order_id"])
            self.assertEqual(len(journal.path.read_text().splitlines()), 1)

    def test_offline_broker_performs_no_network_calls(self):
        broker = OfflinePaperBroker({"SPY": 645.36})

        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            response = broker.preview_equity_order("SPY", 1, "BUY")

        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], ExecutionStatus.FILLED.value)

    def test_existing_execution_pipeline_returns_execution_result(self):
        broker = OfflinePaperBroker({"SPY": 645.36})
        engine = ExecutionEngine(OrderRouter(broker))
        request = SignalToTradeBridge().create_request(actionable_signal())

        result = engine.execute(request)

        self.assertIsInstance(result, ExecutionResult)
        self.assertEqual(result.status, ExecutionStatus.FILLED)
        self.assertEqual(result.broker_response["fill_price"], 645.36)

    def test_execution_result_timestamp_originates_from_clock(self):
        expected = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
        request = SignalToTradeBridge().create_request(actionable_signal())

        with patch.object(system_clock, "now", return_value=expected) as clock_now:
            result = ExecutionResult(
                status=ExecutionStatus.REJECTED,
                request=request,
                message="test",
            )

        self.assertEqual(result.timestamp_utc, expected.isoformat())
        clock_now.assert_called_once_with()

    def test_identical_inputs_have_deterministic_execution_semantics(self):
        broker = OfflinePaperBroker({"SPY": 645.36})

        first = broker.preview_equity_order("SPY", 1, "BUY")
        second = broker.preview_equity_order("SPY", 1, "BUY")

        self.assertEqual(first, second)

    def test_journal_writes_one_complete_append_only_record(self):
        with TemporaryDirectory() as directory:
            journal = DecisionJournal(Path(directory) / "decisions.jsonl")
            outcome = PaperDecisionService(journal).execute(
                actionable_signal(),
                self.snapshot(),
            )

            lines = journal.path.read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[0])
            self.assertEqual(len(lines), 1)
            self.assertEqual(record, outcome.record)
            for key in (
                "decision_record_id",
                "timestamp",
                "market_snapshot_id",
                "market_data_id",
                "source_event_sequences",
                "trade_request",
                "execution_result",
                "paper_order_id",
                "fill_quantity",
                "fill_price",
                "trace_id",
                "correlation_id",
                "input_origin",
            ):
                self.assertIn(key, record)

    def test_decision_record_identifies_configured_replay_origin(self):
        with TemporaryDirectory() as directory:
            outcome = PaperDecisionService(
                DecisionJournal(Path(directory) / "decisions.jsonl")
            ).execute(actionable_signal(), self.snapshot())

        self.assertEqual(outcome.record["input_origin"], INPUT_ORIGIN)

    def test_replay_to_record_pipeline_runs_end_to_end(self):
        market_data_bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
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
        market_data_bus.subscribe(builder)
        builder.subscribe(strategy_bridge)
        observations = [
            observation("SPY", 645.12),
            observation("NVDA", 182.44),
            observation("AAPL", 231.08),
            observation("SPY", 645.36),
        ]
        list(ReplaySource(observations).run(market_data_bus))
        snapshot = builder.build()

        with TemporaryDirectory() as directory:
            outcome = PaperDecisionService(
                DecisionJournal(Path(directory) / "decisions.jsonl")
            ).execute(strategy_bridge.last_signals[0], snapshot)

        self.assertEqual(outcome.execution_result.status, ExecutionStatus.FILLED)
        self.assertEqual(outcome.record["fill_price"], 645.36)
        self.assertEqual(outcome.record["source_event_sequences"], [4])


if __name__ == "__main__":
    unittest.main()
