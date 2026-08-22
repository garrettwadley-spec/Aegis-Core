"""Focused LAUNCH-008R historical OHLCV replay tests."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    PER_BAR_VOLUME,
    REAL_HISTORICAL_FACTOR_ORIGIN,
    REAL_HISTORICAL_LEARNING_ELIGIBILITY,
    CanonicalMarketHistory,
    HistoricalBarReplayAdapter,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    OpeningRangeFactors,
    RawMarketData,
    determine_volume_semantics,
    file_sha256,
    load_stooq_style_bars,
    normalize_market_data,
    validate_timezone_sessions,
)
from aegis.outcomes import OutcomeJournal, OutcomeObserver
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import MarketSignal, OpeningRangeStrategy
from scripts.run_real_historical_orb_replay import (
    _claim_session_once,
    run_replay,
)


HEADER = (
    "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,"
    "<CLOSE>,<VOL>,<OPENINT>\n"
)


def write_source(path: Path, rows: tuple[str, ...]) -> None:
    path.write_text(HEADER + "".join(rows), encoding="utf-8")


def quote(**overrides) -> RawMarketData:
    values = {
        "symbol": "SPY",
        "exchange": "ARCX",
        "bid": 99.9,
        "ask": 100.1,
        "last": 100.0,
        "volume": 100.0,
        "source": "test",
        "source_timestamp": "2026-01-05T14:30:00Z",
    }
    values.update(overrides)
    return RawMarketData(**values)


def historical(
    *,
    last: float,
    volume: float,
    timestamp: datetime,
    source_open: float,
    row: int,
) -> RawMarketData:
    return RawMarketData(
        symbol="SPY",
        exchange="",
        bid=None,
        ask=None,
        last=last,
        volume=volume,
        source="real-historical-local-ohlcv",
        source_timestamp=timestamp,
        metadata={
            "observation_type": "OHLCV_BAR",
            "source_open": source_open,
            "source_high": max(source_open, last),
            "source_low": min(source_open, last),
            "source_close": last,
            "source_bar_volume": volume,
            "derived_cumulative_session_volume": volume,
            "source_timezone": "Europe/Warsaw",
            "normalized_utc_timestamp": timestamp.isoformat(),
            "normalized_new_york_timestamp": timestamp.isoformat(),
            "source_file": "C:/data/spy.us.txt",
            "source_file_sha256": "A" * 64,
            "source_row_identifier": f"line:{row}",
            "source_provider": "Stooq-style local archive",
            "source_provider_confidence": "MEDIUM",
            "source_symbol": "SPY.US",
            "source_session": timestamp.date().isoformat(),
            "volume_semantics": "PER_BAR",
            "code_commit": "abc123",
        },
    )


class TestHistoricalQuoteContract(unittest.TestCase):
    def test_historical_bar_may_omit_both_quotes(self):
        market_data = normalize_market_data(quote(bid=None, ask=None))
        self.assertIsNone(market_data.bid)
        self.assertIsNone(market_data.ask)

    def test_single_sided_quote_is_rejected(self):
        for bid, ask in ((1.0, None), (None, 1.0)):
            with self.subTest(bid=bid, ask=ask), self.assertRaises(ValueError):
                normalize_market_data(quote(bid=bid, ask=ask))

    def test_complete_quote_remains_valid(self):
        market_data = normalize_market_data(quote())
        self.assertEqual((market_data.bid, market_data.ask), (99.9, 100.1))

    def test_invalid_present_quotes_are_rejected(self):
        invalid = (
            {"bid": -0.1, "ask": 1.0},
            {"bid": 1.0, "ask": -0.1},
            {"bid": 2.0, "ask": 1.0},
            {"bid": float("nan"), "ask": 1.0},
            {"bid": 1.0, "ask": float("inf")},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                normalize_market_data(quote(**values))

    def test_historical_metadata_is_copied_and_immutable(self):
        metadata = {"source_open": 99.0}
        market_data = normalize_market_data(
            quote(bid=None, ask=None, metadata=metadata)
        )
        metadata["source_open"] = 1.0
        self.assertEqual(market_data.metadata["source_open"], 99.0)
        with self.assertRaises(TypeError):
            market_data.metadata["source_open"] = 2.0  # type: ignore[index]


class TestHistoricalSourceAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.source = Path(self.directory.name) / "spy.us.txt"
        write_source(
            self.source,
            (
                "SPY.US,5,20260105,153000,100,101,99,100.5,200,0\n",
                "SPY.US,5,20260105,215500,101,102,100,101.5,100,0\n",
                "SPY.US,5,20260309,143000,102,103,101,102.5,300,0\n",
                "SPY.US,5,20260309,205500,103,104,102,103.5,150,0\n",
                "SPY.US,5,20260330,153000,104,105,103,104.5,250,0\n",
                "SPY.US,5,20260330,215500,105,106,104,105.5,125,0\n",
            ),
        )
        self.bars = load_stooq_style_bars(self.source)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_warsaw_to_utc_and_new_york_handles_dst_mismatch(self):
        samples = validate_timezone_sessions(
            self.bars,
            (date(2026, 1, 5), date(2026, 3, 9), date(2026, 3, 30)),
        )
        self.assertTrue(all(sample.passed for sample in samples))
        self.assertEqual(samples[0].utc_open.hour, 14)
        self.assertEqual(samples[1].raw_open.hour, 14)
        self.assertEqual(samples[1].new_york_open.hour, 9)
        self.assertEqual(samples[2].raw_open.hour, 15)
        self.assertEqual(samples[2].new_york_open.hour, 9)

    def test_per_bar_volume_is_proven_and_converted_to_cumulative(self):
        semantics = determine_volume_semantics(self.bars)
        self.assertEqual(semantics.classification, PER_BAR_VOLUME)
        adapter = HistoricalBarReplayAdapter(
            self.bars,
            source_file=self.source,
            source_file_sha256=file_sha256(self.source),
            code_commit="abc123",
        )
        observations = tuple(adapter.observations())
        self.assertEqual(
            [item.volume for item in observations],
            [200.0, 300.0, 300.0, 450.0, 250.0, 375.0],
        )
        self.assertEqual(observations[0].metadata["source_bar_volume"], 200.0)

    def test_rows_flow_through_market_data_bus_with_sha_provenance(self):
        adapter = HistoricalBarReplayAdapter(
            self.bars,
            source_file=self.source,
            source_file_sha256=file_sha256(self.source),
            code_commit="abc123",
        )
        bus = MarketDataBus()
        history = CanonicalMarketHistory()
        bus.subscribe(history)
        canonical = [bus.ingest(raw) for raw in adapter.observations()]
        self.assertEqual(len(history.window("SPY")), len(self.bars))
        self.assertEqual(canonical[0].last, self.bars[0].close)
        self.assertEqual(
            canonical[0].metadata["source_file_sha256"],
            file_sha256(self.source),
        )


class TestHistoricalFactorPipeline(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-05T14:30:00+00:00",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_session_open_uses_source_open_and_no_future_sequence(self):
        bus = MarketDataBus()
        history = CanonicalMarketHistory()
        bus.subscribe(history)
        row = 1
        for day in (date(2026, 1, 5), date(2026, 1, 6)):
            start = datetime.combine(day, datetime.min.time(), timezone.utc)
            start += timedelta(hours=14, minutes=30)
            for offset, volume in ((0, 100.0), (10, 200.0)):
                bus.ingest(
                    historical(
                        last=100.0,
                        volume=volume,
                        timestamp=start + timedelta(minutes=offset),
                        source_open=100.0,
                        row=row,
                    )
                )
                row += 1

        current_start = datetime(2026, 1, 7, 14, 30, tzinfo=timezone.utc)
        prices = (100.0, 102.0, 101.0, 103.0, 104.0, 999.0)
        pinned_sequence = None
        for index, price in enumerate(prices):
            bus.ingest(
                historical(
                    last=price,
                    volume=100.0 + index * 100.0,
                    timestamp=current_start + timedelta(seconds=index * 10),
                    source_open=99.0 if index == 0 else price,
                    row=row,
                )
            )
            row += 1
            if index == 4:
                pinned_sequence = history.window("SPY")[-1].sequence_number

        factors = OpeningRangeFactorCalculator(
            history,
            OpeningRangeCalculationConfig(
                rsi_period=2,
                macd_fast_period=2,
                macd_slow_period=3,
                macd_signal_period=2,
                relative_volume_lookback_sessions=2,
            ),
        ).calculate(
            "SPY",
            as_of_sequence=pinned_sequence,
            input_origin=REAL_HISTORICAL_FACTOR_ORIGIN,
        )
        self.assertEqual(factors.session_open_price, 99.0)
        self.assertEqual(factors.current_price, 104.0)
        self.assertLessEqual(max(factors.source_event_sequences), pinned_sequence)

    def test_strategy_thresholds_are_unchanged(self):
        strategy = OpeningRangeStrategy()
        boundary = {
            "symbol": "SPY",
            "relative_volume": 4.0,
            "price_change_pct": 8.0,
            "rsi": 39.999,
            "macd_cross": True,
        }
        self.assertIsNotNone(strategy.evaluate(boundary))
        for key, value in (
            ("relative_volume", 3.999),
            ("price_change_pct", 7.999),
            ("rsi", 40.0),
            ("macd_cross", False),
        ):
            rejected = dict(boundary)
            rejected[key] = value
            self.assertIsNone(strategy.evaluate(rejected))

    def test_session_decision_limit_allows_only_one(self):
        claimed: set[tuple[str, str]] = set()
        self.assertTrue(_claim_session_once(claimed, "SPY", "2026-01-05"))
        self.assertFalse(_claim_session_once(claimed, "SPY", "2026-01-05"))
        self.assertTrue(_claim_session_once(claimed, "SPY", "2026-01-06"))

    def test_decision_and_outcome_preserve_real_dataset_provenance(self):
        bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        bus.subscribe(builder)
        first = bus.ingest(
            historical(
                last=100.0,
                volume=100.0,
                timestamp=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
                source_open=99.0,
                row=2,
            )
        )
        snapshot = builder.build()
        sequence = snapshot.source_event_sequences[0]
        factors = OpeningRangeFactors(
            object_id="ORB-TEST",
            created_at=first.received_at,
            symbol="SPY",
            as_of=first.source_timestamp,
            session_open_price=99.0,
            current_price=100.0,
            relative_volume=4.0,
            price_change_pct=8.0,
            rsi=39.0,
            macd=-1.0,
            macd_signal=-2.0,
            macd_cross_up_below_zero=True,
            source_market_data_ids=(first.object_id,),
            source_event_sequences=(sequence,),
            calculation_config=OpeningRangeCalculationConfig(),
            input_origin=REAL_HISTORICAL_FACTOR_ORIGIN,
            prior_sessions_used=tuple(
                f"2025-12-{day:02d}" for day in range(1, 11)
            ),
        )
        signal = MarketSignal(
            symbol="SPY",
            action="BUY",
            confidence=0.92,
            strategy=OpeningRangeStrategy.name,
        )
        with TemporaryDirectory() as directory:
            decision = PaperDecisionService(
                DecisionJournal(Path(directory) / "decisions.jsonl")
            ).execute(
                signal,
                snapshot,
                opening_range_factors=factors,
                learning_eligibility=(
                    REAL_HISTORICAL_LEARNING_ELIGIBILITY
                ),
            )
            outcome_journal = OutcomeJournal(Path(directory) / "outcomes.jsonl")
            observer = OutcomeObserver(outcome_journal)
            observer.observe_decision(decision)
            bus.subscribe(observer)
            bus.ingest(
                historical(
                    last=101.0,
                    volume=200.0,
                    timestamp=datetime(
                        2026,
                        1,
                        5,
                        14,
                        35,
                        tzinfo=timezone.utc,
                    ),
                    source_open=101.0,
                    row=3,
                )
            )

        provenance = decision.record["dataset_provenance"]
        self.assertEqual(
            decision.record["input_origin"],
            REAL_HISTORICAL_FACTOR_ORIGIN,
        )
        self.assertEqual(
            decision.record["learning_eligibility"],
            REAL_HISTORICAL_LEARNING_ELIGIBILITY,
        )
        self.assertEqual(provenance["source_file_sha256"], "A" * 64)
        self.assertEqual(observer.outcomes[0].source_row_identifier, "line:3")
        self.assertEqual(observer.outcomes[0].code_commit, "abc123")


class TestReplayRunner(unittest.TestCase):
    def test_zero_signal_replay_is_deterministic_and_creates_no_decision(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "spy.us.txt"
            write_source(
                source,
                (
                    "SPY.US,5,20260105,153000,100,101,99,100.5,200,0\n",
                    "SPY.US,5,20260105,215500,101,102,100,101.5,100,0\n",
                ),
            )
            samples = (date(2026, 1, 5),)
            first, _ = run_replay(
                source,
                root / "run-one",
                repository=Path.cwd(),
                code_commit="abc123",
                timezone_samples=samples,
            )
            second, _ = run_replay(
                source,
                root / "run-two",
                repository=Path.cwd(),
                code_commit="abc123",
                timezone_samples=samples,
            )

            self.assertEqual(first["dataset"], second["dataset"])
            self.assertEqual(first["replay"], second["replay"])
            self.assertEqual(first["evidence"], second["evidence"])
            self.assertEqual(first["replay"]["decisions"], 0)
            self.assertEqual(first["replay"]["no_action_sessions"], 0)
            self.assertFalse(
                Path(first["provenance"]["decision_journal"]).exists()
            )


if __name__ == "__main__":
    unittest.main()
