"""Focused tests for the fixed LAUNCH-010 research ablation."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.execution import PaperDecisionService
from aegis.marketdata import (
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactors,
    RawMarketData,
)
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy
from scripts.run_orb_gate_ablation import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    HOLDOUT_END,
    HOLDOUT_START,
    LEARNING_ELIGIBILITY,
    VARIANTS,
    ResearchDecisionJournal,
    _research_signal,
    build_diagnosis,
    claim_variant_session_once,
    compute_run_id,
    finalize_joint_pattern_table,
    leave_one_out_intersections,
    matching_variants,
    new_joint_pattern_table,
    pattern_key,
    record_joint_pattern,
    run_ablation,
    sample_adequacy,
    summarize_variant,
    validate_no_lookahead,
    variant_matches,
    window_for_session,
)
from scripts.run_real_universe_orb_scan import (
    INPUT_ORIGIN,
    price_is_eligible,
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


def historical_observation() -> RawMarketData:
    timestamp = datetime(2026, 1, 5, 14, 35, tzinfo=timezone.utc)
    return RawMarketData(
        symbol="TEST",
        exchange="",
        bid=None,
        ask=None,
        last=5.0,
        volume=1_200_000,
        source="real-historical-local-ohlcv",
        source_timestamp=timestamp,
        metadata={
            "observation_type": "OHLCV_BAR",
            "source_open": 4.5,
            "source_high": 5.0,
            "source_low": 4.5,
            "source_close": 5.0,
            "source_bar_volume": 1_200_000,
            "derived_cumulative_session_volume": 1_200_000,
            "source_timezone": "Europe/Warsaw",
            "normalized_utc_timestamp": timestamp.isoformat(),
            "normalized_new_york_timestamp": timestamp.isoformat(),
            "source_file": "C:/data/test.us.txt",
            "source_file_sha256": "B" * 64,
            "source_row_identifier": "line:2",
            "source_provider": "Stooq-style local archive",
            "source_provider_confidence": "MEDIUM",
            "source_symbol": "TEST.US",
            "source_session": "2026-01-05",
            "source_period_minutes": 5,
            "volume_semantics": "PER_BAR",
            "code_commit": "test-commit",
        },
    )


def factors(sequence: int, *, future: bool = False) -> OpeningRangeFactors:
    return OpeningRangeFactors(
        object_id="ORB-LAUNCH010-TEST",
        created_at=datetime(2026, 1, 5, 14, 35, tzinfo=timezone.utc),
        symbol="TEST",
        as_of=datetime(2026, 1, 5, 14, 35, tzinfo=timezone.utc),
        session_open_price=4.5,
        current_price=5.0,
        relative_volume=4.0,
        price_change_pct=8.0,
        rsi=39.0,
        macd=-0.5,
        macd_signal=-0.6,
        macd_cross_up_below_zero=True,
        source_market_data_ids=("MARKET-DATA-TEST",),
        source_event_sequences=(sequence + 1 if future else sequence,),
        calculation_config=OpeningRangeCalculationConfig(),
        input_origin=INPUT_ORIGIN,
        prior_sessions_used=tuple(
            f"2025-12-{day:02d}" for day in range(1, 11)
        ),
    )


class TestProductionStrategyPreserved(unittest.TestCase):
    def test_production_opening_range_strategy_is_unchanged(self):
        strategy = OpeningRangeStrategy()
        passing = {
            "symbol": "TEST",
            "relative_volume": 4.0,
            "price_change_pct": 8.0,
            "rsi": 39.999,
            "macd_cross": True,
        }
        self.assertIsNotNone(strategy.evaluate(passing))
        for field, failing_value in (
            ("relative_volume", 3.999),
            ("price_change_pct", 7.999),
            ("rsi", 40.0),
            ("macd_cross", False),
        ):
            candidate = dict(passing)
            candidate[field] = failing_value
            self.assertIsNone(strategy.evaluate(candidate))

    def test_all_universe_and_factor_thresholds_remain_unchanged(self):
        self.assertTrue(price_is_eligible(2.50))
        self.assertTrue(price_is_eligible(8.00))
        self.assertFalse(price_is_eligible(2.499))
        self.assertFalse(price_is_eligible(8.001))
        self.assertFalse(volume_is_eligible(1_000_000))
        self.assertTrue(volume_is_eligible(1_000_001))
        config = OpeningRangeCalculationConfig().to_dict()
        self.assertEqual(config["relative_volume_lookback_sessions"], 10)
        self.assertEqual(config["rsi_period"], 14)
        self.assertEqual(config["macd_fast_period"], 12)
        self.assertEqual(config["macd_slow_period"], 26)
        self.assertEqual(config["macd_signal_period"], 9)
        self.assertEqual(config["volume_bucket_minutes"], 10)


class TestPredeclaredVariants(unittest.TestCase):
    def test_exactly_five_fixed_variants_exist(self):
        self.assertEqual(
            tuple(variant.variant_id for variant in VARIANTS),
            ("V0", "V1", "V2", "V3", "V4"),
        )
        with self.assertRaises(FrozenInstanceError):
            VARIANTS[0].name = "changed"

    def test_v1_removes_only_macd(self):
        self.assertEqual(VARIANTS[1].advisory_condition, "macd_cross")
        self.assertEqual(
            VARIANTS[1].required_conditions,
            ("relative_volume", "price_change", "rsi"),
        )

    def test_v2_removes_only_rsi(self):
        self.assertEqual(VARIANTS[2].advisory_condition, "rsi")
        self.assertEqual(
            VARIANTS[2].required_conditions,
            ("relative_volume", "price_change", "macd_cross"),
        )

    def test_v3_removes_only_price_change(self):
        self.assertEqual(VARIANTS[3].advisory_condition, "price_change")
        self.assertEqual(
            VARIANTS[3].required_conditions,
            ("relative_volume", "rsi", "macd_cross"),
        )

    def test_v4_removes_only_relative_volume(self):
        self.assertEqual(VARIANTS[4].advisory_condition, "relative_volume")
        self.assertEqual(
            VARIANTS[4].required_conditions,
            ("price_change", "rsi", "macd_cross"),
        )

    def test_holdout_evidence_cannot_mutate_variant_definitions(self):
        before = tuple(variant.to_dict() for variant in VARIANTS)
        matching_variants(
            {
                "relative_volume": True,
                "price_change": True,
                "rsi": True,
                "macd_cross": False,
            }
        )
        self.assertEqual(before, tuple(variant.to_dict() for variant in VARIANTS))

    def test_variant_matching_changes_only_gate_requirement(self):
        state = {
            "relative_volume": True,
            "price_change": True,
            "rsi": True,
            "macd_cross": False,
        }
        self.assertFalse(variant_matches(VARIANTS[0], state))
        self.assertTrue(variant_matches(VARIANTS[1], state))
        self.assertEqual(
            tuple(variant.variant_id for variant in matching_variants(state)),
            ("V1",),
        )


class TestWindowsAndPatterns(unittest.TestCase):
    def test_development_and_holdout_assignment_is_fixed(self):
        self.assertEqual(window_for_session(DEVELOPMENT_START), "DEVELOPMENT")
        self.assertEqual(window_for_session(DEVELOPMENT_END), "DEVELOPMENT")
        self.assertEqual(window_for_session(HOLDOUT_START), "HOLDOUT")
        self.assertEqual(window_for_session(HOLDOUT_END), "HOLDOUT")
        with self.assertRaises(ValueError):
            window_for_session(date(2026, 3, 14))

    def test_joint_truth_pattern_counts_are_complete_and_correct(self):
        table = new_joint_pattern_table()
        state = {
            "relative_volume": True,
            "price_change": True,
            "rsi": True,
            "macd_cross": False,
        }
        record_joint_pattern(table, state, "DEVELOPMENT")
        record_joint_pattern(table, state, "HOLDOUT")
        baseline = dict(state, macd_cross=True)
        record_joint_pattern(table, baseline, "DEVELOPMENT")
        finalized = finalize_joint_pattern_table(table)
        self.assertEqual(len(finalized), 16)
        self.assertEqual(pattern_key(state), "1110")
        self.assertEqual(table["1110"]["count"], 2)
        self.assertEqual(table["1110"]["development_count"], 1)
        self.assertEqual(table["1110"]["holdout_count"], 1)
        self.assertAlmostEqual(
            table["1110"]["percentage_of_sufficient_history_points"],
            2 / 3,
        )

    def test_leave_one_out_intersections_use_exact_patterns(self):
        table = new_joint_pattern_table()
        expected = {
            "baseline": "1111",
            "no_macd": "1110",
            "no_rsi": "1101",
            "no_price_change": "1011",
            "no_relative_volume": "0111",
        }
        for index, key in enumerate(expected.values(), start=1):
            table[key]["count"] = index
            table[key]["development_count"] = index - 1
            table[key]["holdout_count"] = 1
        result = leave_one_out_intersections(table)
        for index, name in enumerate(expected, start=1):
            self.assertEqual(result[name]["count"], index)


class TestSignalSafety(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-05T14:35:00Z",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_maximum_one_signal_per_symbol_session_variant(self):
        claimed: set[tuple[str, str, str]] = set()
        self.assertTrue(
            claim_variant_session_once(claimed, "V1", "TEST", "2026-01-05")
        )
        self.assertFalse(
            claim_variant_session_once(claimed, "V1", "TEST", "2026-01-05")
        )
        self.assertTrue(
            claim_variant_session_once(claimed, "V2", "TEST", "2026-01-05")
        )

    def test_future_factor_provenance_is_rejected(self):
        validate_no_lookahead(factors(10), 10)
        with self.assertRaises(ValueError):
            validate_no_lookahead(factors(10, future=True), 10)

    def test_every_variant_records_all_factors_conditions_and_context(self):
        bus = MarketDataBus()
        builder = MarketSnapshotBuilder()
        bus.subscribe(builder)
        bus.ingest(historical_observation())
        snapshot = builder.build()
        sequence = snapshot.source_event_sequences[0]
        derived = factors(sequence)
        conditions = {
            "relative_volume": True,
            "price_change": True,
            "rsi": True,
            "macd_cross": True,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths: list[Path] = []
            for variant in VARIANTS:
                path = root / variant.variant_id / "decisions.jsonl"
                journal = ResearchDecisionJournal(path, variant.variant_id)
                journal.set_context(
                    window="DEVELOPMENT",
                    session_date="2026-01-05",
                    evaluation_timestamp=derived.as_of,
                    condition_results=conditions,
                )
                decision = PaperDecisionService(journal).execute(
                    _research_signal(variant, derived, conditions),
                    snapshot,
                    opening_range_factors=derived,
                    learning_eligibility=LEARNING_ELIGIBILITY,
                )
                self.assertIsNotNone(decision)
                record = decision.record
                self.assertEqual(record["variant_id"], variant.variant_id)
                self.assertEqual(record["window"], "DEVELOPMENT")
                self.assertEqual(record["baseline_condition_passes"], conditions)
                self.assertEqual(record["learning_eligibility"], LEARNING_ELIGIBILITY)
                self.assertEqual(
                    set(record["strategy_factors"]),
                    {
                        "session_open_price",
                        "current_price",
                        "relative_volume",
                        "price_change_pct",
                        "rsi",
                        "macd",
                        "macd_signal",
                        "macd_cross_up_below_zero",
                    },
                )
                paths.append(path)
            self.assertEqual(len({path.parent for path in paths}), 5)
            self.assertTrue(all(path.exists() for path in paths))

    def test_zero_match_creates_no_false_decision_journal(self):
        state = {
            name: False
            for name in (
                "relative_volume",
                "price_change",
                "rsi",
                "macd_cross",
            )
        }
        self.assertEqual(matching_variants(state), ())
        with TemporaryDirectory() as directory:
            path = Path(directory) / "V0" / "decisions.jsonl"
            ResearchDecisionJournal(path, "V0")
            self.assertFalse(path.exists())


class TestResultsAndArtifacts(unittest.TestCase):
    def test_sample_adequacy_uses_only_signal_count(self):
        self.assertEqual(sample_adequacy(19, "DEVELOPMENT"), "INSUFFICIENT")
        self.assertEqual(
            sample_adequacy(20, "DEVELOPMENT"),
            "ADEQUATE FOR REVIEW",
        )
        self.assertEqual(sample_adequacy(4, "HOLDOUT"), "INSUFFICIENT")
        self.assertEqual(sample_adequacy(5, "HOLDOUT"), "ADEQUATE FOR REVIEW")

    def test_variant_results_keep_windows_separate(self):
        signals = [
            {
                "variant_id": "V1",
                "window": "DEVELOPMENT",
                "symbol": "AAA",
                "session_date": "2026-01-05",
            },
            {
                "variant_id": "V1",
                "window": "HOLDOUT",
                "symbol": "BBB",
                "session_date": "2026-03-16",
            },
        ]
        outcomes = [
            dict(
                signals[0],
                signed_return=1.0,
                signed_return_pct=0.1,
                directional_correct=True,
            ),
            dict(
                signals[1],
                signed_return=-1.0,
                signed_return_pct=-0.1,
                directional_correct=False,
            ),
        ]
        development = summarize_variant(
            VARIANTS[1], "DEVELOPMENT", 100, signals, outcomes
        )
        holdout = summarize_variant(
            VARIANTS[1], "HOLDOUT", 50, signals, outcomes
        )
        self.assertEqual(development["signals"], 1)
        self.assertEqual(development["profitable"], 1)
        self.assertEqual(holdout["signals"], 1)
        self.assertEqual(holdout["unprofitable"], 1)

    def test_diagnosis_does_not_promote_or_claim_profitability(self):
        def result(signals: int, adequate: bool = False) -> dict:
            return {
                "signals": signals,
                "directional_accuracy": 0.6 if signals else None,
                "sample_adequacy": (
                    "ADEQUATE FOR REVIEW" if adequate else "INSUFFICIENT"
                ),
            }

        combined = {f"V{i}": result(i * 10) for i in range(5)}
        development = {f"V{i}": result(i * 5, i == 4) for i in range(5)}
        holdout = {f"V{i}": result(i, i == 4) for i in range(5)}
        intersections = {
            name: {"count": count}
            for name, count in (
                ("baseline", 0),
                ("no_macd", 10),
                ("no_rsi", 2),
                ("no_price_change", 3),
                ("no_relative_volume", 4),
            )
        }
        diagnosis = build_diagnosis(
            combined,
            development,
            holdout,
            intersections,
        )
        self.assertFalse(diagnosis["profitability_claim_justified"])
        self.assertFalse(diagnosis["production_strategy_changed"])
        self.assertEqual(
            diagnosis["controlled_validation_candidates_by_sample_count"],
            ["V4"],
        )

    def test_debug_replay_is_deterministic_and_writes_required_artifacts(self):
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
            first, output = run_ablation(
                source_root,
                root / "run-one",
                repository=Path.cwd(),
                code_commit="test-commit",
                maximum_files=1,
            )
            second, _ = run_ablation(
                source_root,
                root / "run-two",
                repository=Path.cwd(),
                code_commit="test-commit",
                maximum_files=1,
            )
            run_directory = Path(first["artifact_directory"])
            self.assertEqual(
                first["manifest"]["run_id"],
                second["manifest"]["run_id"],
            )
            self.assertEqual(
                first["joint_condition_patterns"],
                second["joint_condition_patterns"],
            )
            for name in (
                "manifest.json",
                "joint_condition_patterns.json",
                "variant_summary.json",
                "development_results.json",
                "holdout_results.json",
                "signals.jsonl",
                "outcomes.jsonl",
                "diagnosis.json",
            ):
                self.assertTrue((run_directory / name).exists())
            self.assertEqual((run_directory / "signals.jsonl").read_text(), "")
            self.assertEqual((run_directory / "outcomes.jsonl").read_text(), "")
            self.assertIn(
                "BASELINE REMAINS NON-OPERATIONAL IN THE APPROVED UNIVERSE",
                output,
            )

        ignore_text = (Path.cwd() / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("runs/", ignore_text)

    def test_run_identity_is_reproducible(self):
        values = {
            "source_manifest_hash": "A" * 64,
            "code_commit": "abc123",
            "factor_config": OpeningRangeCalculationConfig().to_dict(),
            "maximum_files": None,
        }
        self.assertEqual(compute_run_id(**values), compute_run_id(**values))


if __name__ == "__main__":
    unittest.main()
