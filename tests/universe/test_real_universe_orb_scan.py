"""Focused tests for the fixed LAUNCH-009 historical universe scan."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    CanonicalMarketHistory,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    OpeningRangeFactors,
    RawMarketData,
)
from aegis.outcomes import OutcomeJournal, OutcomeObserver
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import MarketSignal, OpeningRangeStrategy
from scripts.run_real_universe_orb_scan import (
    CONDITION_ORDER,
    EVALUATION_END,
    EVALUATION_START,
    INPUT_ORIGIN,
    LEARNING_ELIGIBILITY,
    UniverseFile,
    _claim_session_once,
    _near_miss_record,
    compute_run_id,
    discover_equity_universe,
    is_completed_ten_minute_boundary,
    near_miss_sort_key,
    price_is_eligible,
    retain_near_miss,
    run_scan,
    scan_evaluation_boundaries,
    volume_is_eligible,
)


HEADER = (
    "<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,"
    "<CLOSE>,<VOL>,<OPENINT>\n"
)


def write_source(path: Path, rows: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "".join(rows), encoding="utf-8")


def source_row(
    symbol: str,
    day: str,
    source_time: str,
    close: float,
    volume: float,
) -> str:
    return (
        f"{symbol}.US,5,{day},{source_time},{close},{close + 0.1},"
        f"{close - 0.1},{close},{volume},0\n"
    )


def historical_observation(
    *,
    last: float,
    volume: float,
    timestamp: datetime,
    row: int,
) -> RawMarketData:
    return RawMarketData(
        symbol="TEST",
        exchange="",
        bid=None,
        ask=None,
        last=last,
        volume=volume,
        source="real-historical-local-ohlcv",
        source_timestamp=timestamp,
        metadata={
            "observation_type": "OHLCV_BAR",
            "source_open": last,
            "source_high": last,
            "source_low": last,
            "source_close": last,
            "source_bar_volume": volume,
            "derived_cumulative_session_volume": volume,
            "source_timezone": "Europe/Warsaw",
            "normalized_utc_timestamp": timestamp.isoformat(),
            "normalized_new_york_timestamp": timestamp.isoformat(),
            "source_file": "C:/data/test.us.txt",
            "source_file_sha256": "B" * 64,
            "source_row_identifier": f"line:{row}",
            "source_provider": "Stooq-style local archive",
            "source_provider_confidence": "MEDIUM",
            "source_symbol": "TEST.US",
            "source_session": timestamp.date().isoformat(),
            "source_period_minutes": 5,
            "volume_semantics": "PER_BAR",
            "code_commit": "test-commit",
        },
    )


class TestUniverseDefinition(unittest.TestCase):
    def test_stock_directories_are_included_deterministically(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(
                root / "nyse stocks/2/zzz.us.txt",
                (source_row("ZZZ", "20260105", "153000", 5.0, 1.0),),
            )
            write_source(
                root / "nasdaq stocks/1/aaa.us.txt",
                (source_row("AAA", "20260105", "153000", 5.0, 1.0),),
            )
            inventory = discover_equity_universe(root)

        self.assertEqual(
            [item.symbol for item in inventory.files],
            ["AAA", "ZZZ"],
        )
        self.assertEqual(inventory.duplicate_symbol_count, 0)

    def test_explicit_etf_directories_are_excluded(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_source(
                root / "nasdaq stocks/1/aaa.us.txt",
                (source_row("AAA", "20260105", "153000", 5.0, 1.0),),
            )
            write_source(
                root / "nasdaq etfs/spy.us.txt",
                (source_row("SPY", "20260105", "153000", 5.0, 1.0),),
            )
            inventory = discover_equity_universe(root)

        self.assertEqual([item.symbol for item in inventory.files], ["AAA"])
        self.assertEqual(inventory.excluded_file_count, 1)

    def test_duplicate_symbol_handling_is_lexicographic(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "nyse stocks/1/dup.us.txt",
                "nasdaq stocks/1/dup.us.txt",
            ):
                write_source(
                    root / relative,
                    (source_row("DUP", "20260105", "153000", 5.0, 1.0),),
                )
            inventory = discover_equity_universe(root)

        self.assertEqual(len(inventory.files), 1)
        self.assertEqual(
            inventory.files[0].relative_path,
            "nasdaq stocks/1/dup.us.txt",
        )
        self.assertEqual(inventory.duplicate_symbol_count, 1)


class TestFixedEvaluationRules(unittest.TestCase):
    def test_period_cadence_and_independent_counts_are_fixed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nasdaq stocks/1/test.us.txt"
            write_source(
                path,
                (
                    source_row("TEST", "20260102", "153500", 5.0, 2_000_000),
                    source_row("TEST", "20260105", "153000", 2.49, 600_000),
                    source_row("TEST", "20260105", "153500", 2.50, 500_001),
                    source_row("TEST", "20260105", "154000", 4.00, 10),
                    source_row("TEST", "20260105", "154500", 8.00, 10),
                    source_row("TEST", "20260105", "155000", 8.00, 10),
                    source_row("TEST", "20260105", "155500", 8.01, 10),
                    source_row("TEST", "20260424", "153500", 5.0, 2_000_000),
                ),
            )
            item = UniverseFile("TEST", path, "nasdaq stocks/1/test.us.txt")
            scan = scan_evaluation_boundaries(item)

        self.assertEqual((EVALUATION_START, EVALUATION_END), (date(2026, 1, 5), date(2026, 4, 23)))
        self.assertEqual(scan.evaluation_points, 3)
        self.assertEqual(scan.independent_counts["price_range"], 2)
        self.assertEqual(scan.independent_counts["cumulative_session_volume"], 3)
        self.assertEqual(scan.funnel_counts["price_range"], 2)
        self.assertEqual(scan.funnel_counts["cumulative_session_volume"], 2)
        self.assertEqual(sorted(scan.eligible_rows), ["line:4", "line:6"])

    def test_completed_boundary_uses_five_minute_bar_end(self):
        at_open = historical_observation(
            last=5.0,
            volume=1.0,
            timestamp=datetime(2026, 1, 5, 9, 30, tzinfo=timezone.utc),
            row=2,
        )
        second_bar = historical_observation(
            last=5.0,
            volume=2.0,
            timestamp=datetime(2026, 1, 5, 9, 35, tzinfo=timezone.utc),
            row=3,
        )
        self.assertFalse(is_completed_ten_minute_boundary(at_open)[0])
        self.assertTrue(is_completed_ten_minute_boundary(second_bar)[0])

    def test_price_and_volume_filters_use_approved_boundaries(self):
        self.assertTrue(price_is_eligible(2.50))
        self.assertTrue(price_is_eligible(8.00))
        self.assertFalse(price_is_eligible(2.49))
        self.assertFalse(price_is_eligible(8.01))
        self.assertFalse(volume_is_eligible(1_000_000))
        self.assertTrue(volume_is_eligible(1_000_001))

    def test_sequential_funnel_order_is_fixed(self):
        self.assertEqual(
            CONDITION_ORDER,
            (
                "valid_regular_session_observation",
                "price_range",
                "cumulative_session_volume",
                "sufficient_factor_history",
                "relative_volume",
                "price_change",
                "rsi",
                "macd_cross",
                "complete_actionable_signal",
            ),
        )

    def test_one_decision_per_symbol_session(self):
        claimed: set[tuple[str, str]] = set()
        self.assertTrue(_claim_session_once(claimed, "TEST", "2026-01-05"))
        self.assertFalse(_claim_session_once(claimed, "TEST", "2026-01-05"))
        self.assertTrue(_claim_session_once(claimed, "TEST", "2026-01-06"))

    def test_unchanged_strategy_thresholds(self):
        strategy = OpeningRangeStrategy()
        approved = {
            "symbol": "TEST",
            "relative_volume": 4.0,
            "price_change_pct": 8.0,
            "rsi": 39.999,
            "macd_cross": True,
        }
        self.assertIsNotNone(strategy.evaluate(approved))
        rejected = dict(approved, rsi=40.0)
        self.assertIsNone(strategy.evaluate(rejected))


class TestNoLookahead(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-05T14:30:00Z",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_factors_are_pinned_before_future_observation(self):
        bus = MarketDataBus()
        history = CanonicalMarketHistory()
        bus.subscribe(history)
        row = 2
        for day in (date(2026, 1, 5), date(2026, 1, 6)):
            start = datetime(day.year, day.month, day.day, 14, 30, tzinfo=timezone.utc)
            for minute, volume in ((0, 100.0), (10, 200.0)):
                bus.ingest(
                    historical_observation(
                        last=5.0,
                        volume=volume,
                        timestamp=start + timedelta(minutes=minute),
                        row=row,
                    )
                )
                row += 1
        start = datetime(2026, 1, 7, 14, 30, tzinfo=timezone.utc)
        pinned = None
        for index, price in enumerate((5.0, 5.2, 5.1, 5.3, 5.4, 99.0)):
            bus.ingest(
                historical_observation(
                    last=price,
                    volume=100.0 + index * 100.0,
                    timestamp=start + timedelta(seconds=index * 10),
                    row=row,
                )
            )
            row += 1
            if index == 4:
                pinned = history.window("TEST")[-1].sequence_number
        factors = OpeningRangeFactorCalculator(
            history,
            OpeningRangeCalculationConfig(
                rsi_period=2,
                macd_fast_period=2,
                macd_slow_period=3,
                macd_signal_period=2,
                relative_volume_lookback_sessions=2,
            ),
        ).calculate("TEST", as_of_sequence=pinned, input_origin=INPUT_ORIGIN)
        self.assertEqual(factors.current_price, 5.4)
        self.assertLessEqual(max(factors.source_event_sequences), pinned)


class TestNearMissEvidence(unittest.TestCase):
    def test_ranking_is_pass_count_then_symbol_date_time(self):
        records = [
            {
                "strategy_conditions_passed_count": count,
                "symbol": symbol,
                "session_date": "2026-01-05",
                "evaluation_timestamp": timestamp,
            }
            for count, symbol, timestamp in (
                (2, "ZZZ", "2026-01-05T15:00:00Z"),
                (3, "BBB", "2026-01-05T15:00:00Z"),
                (3, "AAA", "2026-01-05T16:00:00Z"),
                (3, "AAA", "2026-01-05T15:00:00Z"),
            )
        ]
        retained: list[dict] = []
        for record in records:
            retain_near_miss(retained, record, limit=3)
        self.assertEqual(retained, sorted(records, key=near_miss_sort_key)[:3])


class TestArtifactsAndPipeline(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-05T14:30:00Z",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_real_signal_uses_existing_decision_and_outcome_pipeline(self):
        bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        bus.subscribe(builder)
        first = bus.ingest(
            historical_observation(
                last=5.0,
                volume=1_100_000,
                timestamp=datetime(2026, 1, 5, 14, 35, tzinfo=timezone.utc),
                row=2,
            )
        )
        snapshot = builder.build()
        sequence = snapshot.source_event_sequences[0]
        factors = OpeningRangeFactors(
            object_id="ORB-LAUNCH009-TEST",
            created_at=first.received_at,
            symbol="TEST",
            as_of=first.source_timestamp,
            session_open_price=4.5,
            current_price=5.0,
            relative_volume=4.0,
            price_change_pct=8.0,
            rsi=39.0,
            macd=-1.0,
            macd_signal=-2.0,
            macd_cross_up_below_zero=True,
            source_market_data_ids=(first.object_id,),
            source_event_sequences=(sequence,),
            calculation_config=OpeningRangeCalculationConfig(),
            input_origin=INPUT_ORIGIN,
            prior_sessions_used=tuple(
                f"2025-12-{day:02d}" for day in range(1, 11)
            ),
        )
        signal = MarketSignal(
            symbol="TEST",
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
                learning_eligibility=LEARNING_ELIGIBILITY,
            )
            observer = OutcomeObserver(
                OutcomeJournal(Path(directory) / "outcomes.jsonl")
            )
            observer.observe_decision(decision)
            bus.subscribe(observer)
            bus.ingest(
                historical_observation(
                    last=5.1,
                    volume=1_200_000,
                    timestamp=datetime(
                        2026,
                        1,
                        5,
                        14,
                        40,
                        tzinfo=timezone.utc,
                    ),
                    row=3,
                )
            )

        self.assertEqual(decision.record["input_origin"], INPUT_ORIGIN)
        self.assertEqual(
            decision.record["learning_eligibility"],
            LEARNING_ELIGIBILITY,
        )
        self.assertEqual(observer.outcomes[0].learning_eligibility, LEARNING_ELIGIBILITY)

    def test_zero_signal_run_writes_reproducible_ignored_artifacts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "source"
            write_source(
                source_root / "nasdaq stocks/1/test.us.txt",
                (
                    source_row("TEST", "20260105", "153000", 100.0, 600_000),
                    source_row("TEST", "20260105", "153500", 100.0, 600_000),
                ),
            )
            first, output = run_scan(
                source_root,
                root / "run-one",
                repository=Path.cwd(),
                code_commit="test-commit",
            )
            second, _ = run_scan(
                source_root,
                root / "run-two",
                repository=Path.cwd(),
                code_commit="test-commit",
            )
            first_run = next((root / "run-one").iterdir())

            self.assertEqual(first["run_id"], second["run_id"])
            self.assertEqual(first["attrition"], second["attrition"])
            self.assertEqual(first["signals"]["paper_decisions"], 0)
            self.assertIn(
                "UNCHANGED STRATEGY GENERATED ZERO SIGNALS",
                output,
            )
            for name in (
                "manifest.json",
                "universe_summary.json",
                "attrition_funnel.json",
                "near_misses.jsonl",
                "summary.json",
            ):
                self.assertTrue((first_run / name).exists())
            self.assertFalse((first_run / "decisions.jsonl").exists())
            self.assertFalse((first_run / "outcomes.jsonl").exists())
            manifest = json_load(first_run / "manifest.json")
            self.assertEqual(manifest["evaluation_period"]["start"], "2026-01-05")
            self.assertEqual(manifest["strategy"]["condition_order"], list(CONDITION_ORDER))

        ignore_text = (Path.cwd() / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("runs/", ignore_text)

    def test_insufficient_history_is_recorded(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "source"
            write_source(
                source_root / "nasdaq stocks/1/test.us.txt",
                (
                    source_row("TEST", "20260105", "153000", 5.0, 600_000),
                    source_row("TEST", "20260105", "153500", 5.0, 600_001),
                ),
            )
            summary, _ = run_scan(
                source_root,
                root / "run",
                repository=Path.cwd(),
                code_commit="test-commit",
            )

        self.assertEqual(
            summary["processing"]["factor_history"]["symbol_statuses"],
            [
                {
                    "symbol": "TEST",
                    "status": "INSUFFICIENT_HISTORY",
                    "factor_attempts": 1,
                }
            ],
        )

    def test_run_identity_is_reproducible(self):
        values = {
            "source_manifest_hash": "A" * 64,
            "code_commit": "abc123",
            "factor_config": OpeningRangeCalculationConfig().to_dict(),
            "maximum_files": None,
        }
        self.assertEqual(compute_run_id(**values), compute_run_id(**values))


def json_load(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
