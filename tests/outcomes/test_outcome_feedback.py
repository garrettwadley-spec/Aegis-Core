"""Focused tests for the first autonomous outcome feedback loop."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    MARKET_DATA_RECEIVED,
    MarketDataBus,
    RawMarketData,
    ReplaySource,
    normalize_market_data,
)
from aegis.outcomes import (
    EVALUATION_HORIZON,
    LEARNING_ELIGIBILITY,
    OutcomeJournal,
    OutcomeObserver,
    evaluate_decision_outcome,
    format_feedback_summary,
    summarize_outcomes,
)
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


def observation(symbol: str = "SPY", last: float = 101.0) -> RawMarketData:
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


def decision_record(
    action: str = "BUY",
    entry_price: float = 100.0,
    quantity: int = 2,
    decision_id: str = "DECISION-1",
    source_sequence: int = 10,
) -> dict:
    return {
        "decision_record_id": decision_id,
        "symbol": "SPY",
        "strategy_action": action,
        "fill_price": entry_price,
        "fill_quantity": quantity,
        "source_event_sequences": [source_sequence],
        "status": "filled",
        "trace_id": "trace-1",
        "correlation_id": "correlation-1",
        "input_origin": "DETERMINISTIC_REPLAY_WITH_CONFIGURED_STRATEGY_FACTORS",
    }


def event(symbol: str, last: float, sequence: int) -> Event:
    market_data = normalize_market_data(observation(symbol, last))
    return Event.create(MARKET_DATA_RECEIVED, market_data).with_sequence(sequence)


class TestOutcomeScoring(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def outcome(self, action: str, mark: float):
        market_data = normalize_market_data(observation(last=mark))
        return evaluate_decision_outcome(
            decision_record(action=action),
            market_data,
            11,
        )

    def test_buy_profit_is_positive(self):
        outcome = self.outcome("BUY", 101.0)
        self.assertEqual(outcome.signed_return, 2.0)
        self.assertAlmostEqual(outcome.signed_return_pct, 0.01)
        self.assertTrue(outcome.directional_correct)

    def test_buy_loss_is_negative(self):
        outcome = self.outcome("BUY", 99.0)
        self.assertEqual(outcome.signed_return, -2.0)
        self.assertFalse(outcome.directional_correct)

    def test_sell_profit_is_positive(self):
        outcome = self.outcome("SELL", 99.0)
        self.assertEqual(outcome.signed_return, 2.0)
        self.assertTrue(outcome.directional_correct)

    def test_sell_loss_is_negative(self):
        outcome = self.outcome("SELL", 101.0)
        self.assertEqual(outcome.signed_return, -2.0)
        self.assertFalse(outcome.directional_correct)

    def test_flat_price_has_no_directional_classification(self):
        outcome = self.outcome("BUY", 100.0)
        self.assertEqual(outcome.signed_return, 0.0)
        self.assertEqual(outcome.signed_return_pct, 0.0)
        self.assertIsNone(outcome.directional_correct)

    def test_outcome_is_immutable(self):
        outcome = self.outcome("BUY", 101.0)
        with self.assertRaises(FrozenInstanceError):
            outcome.mark_price = 102.0  # type: ignore[misc]

    def test_outcome_links_decision_and_market_provenance(self):
        market_data = normalize_market_data(observation(last=101.0))
        outcome = evaluate_decision_outcome(
            decision_record(decision_id="DECISION-LINK"),
            market_data,
            14,
        )
        self.assertEqual(outcome.decision_record_id, "DECISION-LINK")
        self.assertEqual(outcome.source_market_data_id, market_data.object_id)
        self.assertEqual(outcome.source_event_sequence, 14)

    def test_truthful_learning_provenance_is_recorded(self):
        outcome = self.outcome("BUY", 101.0)
        self.assertEqual(
            outcome.input_origin,
            "DETERMINISTIC_REPLAY_WITH_CONFIGURED_STRATEGY_FACTORS",
        )
        self.assertEqual(outcome.learning_eligibility, LEARNING_ELIGIBILITY)
        self.assertEqual(outcome.evaluation_horizon, EVALUATION_HORIZON)

    def test_evaluated_at_originates_from_clock(self):
        expected = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
        market_data = normalize_market_data(observation(last=101.0))

        with patch.object(system_clock, "now", return_value=expected) as clock_now:
            outcome = evaluate_decision_outcome(
                decision_record(),
                market_data,
                11,
            )

        self.assertEqual(outcome.evaluated_at, expected)
        clock_now.assert_called_once_with()


class TestOutcomeObserver(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )
        self.directory = TemporaryDirectory()
        self.journal = OutcomeJournal(Path(self.directory.name) / "outcomes.jsonl")
        self.observer = OutcomeObserver(self.journal)
        self.observer.observe_decision(decision_record())

    def tearDown(self) -> None:
        self.directory.cleanup()
        system_clock.set_mode(ClockMode.LIVE)

    def test_other_symbols_do_not_trigger_evaluation(self):
        self.observer.receive(event("NVDA", 101.0, 11))
        self.assertEqual(self.observer.outcomes, ())
        self.assertEqual(self.journal.records(), [])

    def test_pre_decision_observations_do_not_trigger_evaluation(self):
        self.observer.receive(event("SPY", 101.0, 10))
        self.assertEqual(self.observer.outcomes, ())

    def test_first_eligible_later_observation_is_used(self):
        self.observer.receive(event("SPY", 101.0, 11))
        self.observer.receive(event("SPY", 102.0, 12))
        self.assertEqual(len(self.observer.outcomes), 1)
        self.assertEqual(self.observer.outcomes[0].mark_price, 101.0)
        self.assertEqual(self.observer.outcomes[0].source_event_sequence, 11)

    def test_decision_is_evaluated_exactly_once_across_observers(self):
        self.observer.receive(event("SPY", 101.0, 11))
        restarted = OutcomeObserver(self.journal)
        self.assertFalse(restarted.observe_decision(decision_record()))
        restarted.receive(event("SPY", 102.0, 12))
        self.assertEqual(len(self.journal.records()), 1)

    def test_outcome_journal_is_append_only(self):
        self.observer.receive(event("SPY", 101.0, 11))
        second = OutcomeObserver(self.journal)
        second.observe_decision(
            decision_record(decision_id="DECISION-2", source_sequence=20)
        )
        second.receive(event("SPY", 102.0, 21))
        records = self.journal.records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["decision_record_id"], "DECISION-1")
        self.assertEqual(records[1]["decision_record_id"], "DECISION-2")

    def test_feedback_summary_reads_accumulated_outcomes(self):
        self.observer.receive(event("SPY", 101.0, 11))
        summary = summarize_outcomes(self.journal.path)
        self.assertEqual(summary.evaluated, 1)
        self.assertEqual(summary.profitable, 1)
        self.assertEqual(summary.unprofitable, 0)
        self.assertEqual(summary.flat, 0)
        self.assertEqual(summary.directional_accuracy, 1.0)
        self.assertEqual(summary.cumulative_signed_return, 2.0)
        self.assertIn("Paper Return: +$2.00", format_feedback_summary(summary))

    def test_complete_replay_decision_outcome_flow_runs_offline(self):
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
        list(
            ReplaySource(
                [
                    observation("SPY", 645.12),
                    observation("NVDA", 182.44),
                    observation("AAPL", 231.08),
                    observation("SPY", 645.36),
                ]
            ).run(market_data_bus)
        )
        snapshot = builder.build()
        decision = PaperDecisionService(
            DecisionJournal(Path(self.directory.name) / "decisions.jsonl")
        ).execute(strategy_bridge.last_signals[0], snapshot)
        outcome_observer = OutcomeObserver(self.journal)
        outcome_observer.observe_decision(decision)
        market_data_bus.subscribe(outcome_observer)

        later = market_data_bus.ingest(observation("SPY", 646.36))

        outcome = outcome_observer.outcomes[0]
        self.assertEqual(outcome.source_market_data_id, later.object_id)
        self.assertEqual(outcome.source_event_sequence, 6)
        self.assertAlmostEqual(outcome.signed_return, 1.0)
        self.assertTrue(outcome.directional_correct)


if __name__ == "__main__":
    unittest.main()
