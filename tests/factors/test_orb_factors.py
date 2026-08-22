"""Focused tests for market-derived Opening Range factors."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    CANONICAL_REPLAY_STRATEGY_EVIDENCE,
    MARKET_DATA_RECEIVED,
    SYNTHETIC_FACTOR_ORIGIN,
    CanonicalMarketHistory,
    InsufficientHistoryError,
    InvalidMarketHistoryError,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    RawMarketData,
    ReplaySource,
    calculate_macd,
    calculate_wilder_rsi,
    normalize_market_data,
)
from aegis.outcomes import OutcomeJournal, OutcomeObserver, summarize_outcomes
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


SYMBOL = "AEGIS-DEMO"
PRIOR_DATES = (
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 1, 9),
    date(2026, 1, 12),
    date(2026, 1, 13),
    date(2026, 1, 14),
    date(2026, 1, 15),
    date(2026, 1, 16),
)


def raw(
    *,
    last: float,
    volume: float,
    source_timestamp: datetime,
    symbol: str = SYMBOL,
) -> RawMarketData:
    return RawMarketData(
        symbol=symbol,
        exchange="XNAS",
        bid=last - 0.02,
        ask=last + 0.02,
        last=last,
        volume=volume,
        source="synthetic-replay",
        source_timestamp=source_timestamp,
    )


def at_session_time(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def demo_prices() -> tuple[float, ...]:
    peak = 140.6286067155259
    trough = 106.46743994392972
    final = 108.01143630133951
    rising = tuple(100.0 + (peak - 100.0) * index / 4 for index in range(5))
    declining = tuple(
        peak + (trough - peak) * index / 47
        for index in range(1, 48)
    )
    rebound = tuple(
        trough + (final - trough) * index / 3
        for index in range(1, 4)
    )
    return rising + declining + rebound


def compact_config(lookback: int = 2) -> OpeningRangeCalculationConfig:
    return OpeningRangeCalculationConfig(
        rsi_period=2,
        macd_fast_period=2,
        macd_slow_period=3,
        macd_signal_period=2,
        relative_volume_lookback_sessions=lookback,
    )


def build_factor_fixture(
    prices: tuple[float, ...],
    *,
    prior_deltas: tuple[float, ...],
    current_delta: float,
    config: OpeningRangeCalculationConfig,
    include_premarket: bool = False,
):
    market_data_bus = MarketDataBus()
    history = CanonicalMarketHistory()
    builder = MarketSnapshotBuilder()
    market_data_bus.subscribe(history)
    market_data_bus.subscribe(builder)

    observations: list[RawMarketData] = []
    for day, bucket_volume in zip(PRIOR_DATES, prior_deltas):
        observations.extend(
            (
                raw(
                    last=100.0,
                    volume=100.0,
                    source_timestamp=at_session_time(day, 14, 30),
                ),
                raw(
                    last=100.0,
                    volume=100.0 + bucket_volume,
                    source_timestamp=at_session_time(day, 14, 40),
                ),
            )
        )

    current_day = date(2026, 1, 20)
    start = at_session_time(current_day, 14, 30)
    if include_premarket:
        observations.append(
            raw(
                last=50.0,
                volume=50.0,
                source_timestamp=at_session_time(current_day, 14, 29),
            )
        )
    denominator = max(len(prices) - 1, 1)
    observations.extend(
        raw(
            last=price,
            volume=100.0 + (current_delta * index / denominator),
            source_timestamp=start + timedelta(seconds=index * 10),
        )
        for index, price in enumerate(prices)
    )
    list(ReplaySource(observations).run(market_data_bus))
    snapshot = builder.build()
    factors = OpeningRangeFactorCalculator(history, config).calculate(
        SYMBOL,
        input_origin=SYNTHETIC_FACTOR_ORIGIN,
    )
    return market_data_bus, history, builder, snapshot, factors


def compact_factor(**kwargs):
    options = {
        "prices": (100.0, 102.0, 101.0, 103.0, 104.0),
        "prior_deltas": (100.0, 200.0),
        "current_delta": 400.0,
        "config": compact_config(),
    }
    options.update(kwargs)
    return build_factor_fixture(**options)


def demo_factor_fixture():
    return build_factor_fixture(
        demo_prices(),
        prior_deltas=(200.0,) * 10,
        current_delta=1_000.0,
        config=OpeningRangeCalculationConfig(),
    )


class TestCanonicalMarketHistory(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def history_event(self, sequence: int, last: float) -> Event:
        market_data = normalize_market_data(
            raw(
                last=last,
                volume=float(sequence),
                source_timestamp=at_session_time(date(2026, 1, 20), 14, 30),
            )
        )
        return Event.create(MARKET_DATA_RECEIVED, market_data).with_sequence(
            sequence
        )

    def test_history_preserves_authoritative_event_ordering(self):
        history = CanonicalMarketHistory()
        history.receive(self.history_event(3, 103.0))
        history.receive(self.history_event(1, 101.0))
        history.receive(self.history_event(2, 102.0))

        self.assertEqual(
            tuple(item.sequence_number for item in history.window(SYMBOL)),
            (1, 2, 3),
        )

    def test_history_preserves_market_data_provenance(self):
        history = CanonicalMarketHistory()
        event = self.history_event(7, 107.0)
        history.receive(event)

        stored = history.window(SYMBOL)[0]
        self.assertEqual(stored.sequence_number, 7)
        self.assertEqual(stored.market_data.object_id, event.payload.object_id)
        self.assertEqual(
            stored.market_data.source_timestamp,
            event.payload.source_timestamp,
        )
        self.assertEqual(stored.market_data.received_at, event.payload.received_at)

    def test_history_is_bounded_and_supports_pinned_queries(self):
        history = CanonicalMarketHistory(max_observations_per_symbol=2)
        for sequence in (1, 2, 3):
            history.receive(self.history_event(sequence, 100.0 + sequence))

        self.assertEqual(
            tuple(item.sequence_number for item in history.window(SYMBOL)),
            (2, 3),
        )
        self.assertEqual(
            tuple(
                item.sequence_number
                for item in history.window(SYMBOL, through_sequence=2)
            ),
            (2,),
        )


class TestIndicatorDefinitions(unittest.TestCase):
    def test_wilder_rsi_matches_reference_series(self):
        prices = (
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
        )
        self.assertAlmostEqual(
            calculate_wilder_rsi(prices),
            70.46413502109705,
            places=12,
        )

    def test_insufficient_rsi_history_fails_explicitly(self):
        with self.assertRaises(InsufficientHistoryError) as raised:
            calculate_wilder_rsi((100.0,) * 14)
        self.assertEqual(raised.exception.factor, "RSI")
        self.assertEqual(raised.exception.required, 15)

    def test_ema_macd_matches_reference_series(self):
        prices = tuple(
            100.0 + (index * 0.2) + (((-1) ** index) * (index % 5) * 0.3)
            for index in range(40)
        )
        result = calculate_macd(prices)
        self.assertAlmostEqual(result.macd, 1.3564594049179703, places=12)
        self.assertAlmostEqual(result.signal, 1.4138112367222277, places=12)
        self.assertAlmostEqual(
            result.previous_macd,
            1.4677298688265807,
            places=12,
        )
        self.assertAlmostEqual(
            result.previous_signal,
            1.428149194673292,
            places=12,
        )

    def test_upward_macd_cross_below_zero_is_detected(self):
        result = calculate_macd(demo_prices())
        self.assertLess(result.macd, 0.0)
        self.assertLessEqual(result.previous_macd, result.previous_signal)
        self.assertGreater(result.macd, result.signal)
        self.assertTrue(result.cross_up_below_zero)

    def test_insufficient_macd_history_fails_explicitly(self):
        with self.assertRaises(InsufficientHistoryError) as raised:
            calculate_macd((100.0,) * 34)
        self.assertEqual(raised.exception.factor, "MACD")
        self.assertEqual(raised.exception.required, 35)


class TestOpeningRangeFactorCalculator(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-05T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_current_regular_session_open_is_selected(self):
        *_, factors = compact_factor(include_premarket=True)
        self.assertEqual(factors.session_open_price, 100.0)

    def test_price_change_percentage_is_calculated(self):
        *_, factors = compact_factor()
        self.assertAlmostEqual(factors.price_change_pct, 4.0)

    def test_ten_minute_cumulative_volume_delta_is_calculated(self):
        *_, factors = compact_factor()
        self.assertAlmostEqual(factors.relative_volume, 400.0 / 150.0)

    def test_same_bucket_prior_sessions_are_selected_newest_first(self):
        *_, factors = compact_factor()
        self.assertEqual(
            factors.prior_sessions_used,
            ("2026-01-06", "2026-01-05"),
        )

    def test_relative_volume_uses_required_prior_session_mean(self):
        *_, factors = compact_factor(
            prior_deltas=(50.0, 150.0),
            current_delta=500.0,
        )
        self.assertAlmostEqual(factors.relative_volume, 5.0)

    def test_decreasing_cumulative_session_volume_is_rejected(self):
        with self.assertRaisesRegex(
            InvalidMarketHistoryError,
            "cumulative volume decreased",
        ):
            compact_factor(current_delta=-10.0)

    def test_zero_historical_average_is_rejected(self):
        with self.assertRaisesRegex(
            InvalidMarketHistoryError,
            "average bucket volume cannot be zero",
        ):
            compact_factor(prior_deltas=(0.0, 0.0))

    def test_insufficient_prior_sessions_fails_explicitly(self):
        with self.assertRaises(InsufficientHistoryError) as raised:
            compact_factor(
                prior_deltas=(100.0,),
                config=compact_config(lookback=2),
            )
        self.assertEqual(raised.exception.factor, "relative volume sessions")
        self.assertEqual(raised.exception.available, 1)

    def test_opening_range_factors_are_immutable(self):
        *_, factors = compact_factor()
        with self.assertRaises(FrozenInstanceError):
            factors.rsi = 99.0  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            factors.calculation_config.rsi_period = 99  # type: ignore[misc]

    def test_factor_sources_preserve_ids_and_sequences(self):
        *_, factors = compact_factor()
        self.assertEqual(
            len(factors.source_market_data_ids),
            len(factors.source_event_sequences),
        )
        self.assertEqual(
            factors.source_event_sequences,
            tuple(sorted(factors.source_event_sequences)),
        )

    def test_identical_pinned_history_and_config_is_deterministic(self):
        _, history, _, _, first = compact_factor()
        second = OpeningRangeFactorCalculator(
            history,
            compact_config(),
        ).calculate(SYMBOL, input_origin=SYNTHETIC_FACTOR_ORIGIN)
        self.assertEqual(first, second)


class TestDerivedFactorPipeline(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-05T14:30:00+00:00",
            replay_step_seconds=1.0,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_strategy_bridge_uses_derived_factors_over_fixtures(self):
        _, _, _, snapshot, factors = demo_factor_fixture()
        bridge = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            {
                SYMBOL: {
                    "relative_volume": 0.0,
                    "price_change_pct": 0.0,
                    "rsi": 100.0,
                    "macd_cross": False,
                }
            },
            opening_range_factors={SYMBOL: factors},
        )
        signals = bridge.evaluate(snapshot)
        self.assertEqual(signals[0].action, "BUY")

    def test_market_derived_factors_create_actionable_signal(self):
        _, _, _, snapshot, factors = demo_factor_fixture()
        bridge = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_factors={SYMBOL: factors},
        )
        signals = bridge.evaluate(snapshot)
        self.assertGreaterEqual(factors.relative_volume, 4.0)
        self.assertGreaterEqual(factors.price_change_pct, 8.0)
        self.assertLess(factors.rsi, 40.0)
        self.assertTrue(factors.macd_cross_up_below_zero)
        self.assertEqual(len(factors.prior_sessions_used), 10)
        self.assertEqual(signals[0].symbol, SYMBOL)

    def test_decision_record_preserves_factor_values_and_provenance(self):
        _, _, _, snapshot, factors = demo_factor_fixture()
        signal = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_factors={SYMBOL: factors},
        ).evaluate(snapshot)[0]
        with TemporaryDirectory() as directory:
            decision = PaperDecisionService(
                DecisionJournal(Path(directory) / "decisions.jsonl")
            ).execute(
                signal,
                snapshot,
                opening_range_factors=factors,
            )

        self.assertEqual(
            decision.record["opening_range_factors_id"],
            factors.object_id,
        )
        self.assertEqual(
            decision.record["strategy_factors"]["rsi"],
            factors.rsi,
        )
        self.assertEqual(
            decision.record["factor_source_market_data_ids"],
            list(factors.source_market_data_ids),
        )
        self.assertEqual(
            decision.record["factor_source_event_sequences"],
            list(factors.source_event_sequences),
        )
        self.assertEqual(
            decision.record["factor_calculation_config"],
            factors.calculation_config.to_dict(),
        )
        self.assertEqual(decision.record["input_origin"], SYNTHETIC_FACTOR_ORIGIN)

    def test_learning_eligibility_is_canonical_replay_evidence(self):
        _, _, _, snapshot, factors = demo_factor_fixture()
        signal = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_factors={SYMBOL: factors},
        ).evaluate(snapshot)[0]
        with TemporaryDirectory() as directory:
            decision = PaperDecisionService(
                DecisionJournal(Path(directory) / "decisions.jsonl")
            ).execute(
                signal,
                snapshot,
                opening_range_factors=factors,
            )
        self.assertEqual(
            decision.record["learning_eligibility"],
            CANONICAL_REPLAY_STRATEGY_EVIDENCE,
        )

    def test_replay_factors_decision_and_outcome_runs_offline(self):
        market_data_bus, _, _, snapshot, factors = demo_factor_fixture()
        signal = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_factors={SYMBOL: factors},
        ).evaluate(snapshot)[0]

        with TemporaryDirectory() as directory:
            decision_journal = DecisionJournal(
                Path(directory) / "decisions.jsonl"
            )
            outcome_journal = OutcomeJournal(Path(directory) / "outcomes.jsonl")
            decision = PaperDecisionService(decision_journal).execute(
                signal,
                snapshot,
                opening_range_factors=factors,
            )
            observer = OutcomeObserver(outcome_journal)
            observer.observe_decision(decision)
            market_data_bus.subscribe(observer)
            later = market_data_bus.ingest(
                raw(
                    last=factors.current_price + 1.0,
                    volume=1_200.0,
                    source_timestamp=at_session_time(
                        date(2026, 1, 20),
                        14,
                        39,
                    ),
                )
            )
            summary = summarize_outcomes(outcome_journal.path)

        outcome = observer.outcomes[0]
        self.assertEqual(outcome.source_market_data_id, later.object_id)
        self.assertAlmostEqual(outcome.signed_return, 1.0)
        self.assertTrue(outcome.directional_correct)
        self.assertEqual(
            outcome.learning_eligibility,
            CANONICAL_REPLAY_STRATEGY_EVIDENCE,
        )
        self.assertEqual(summary.evaluated, 1)
        self.assertAlmostEqual(summary.cumulative_signed_return, 1.0)


if __name__ == "__main__":
    unittest.main()
