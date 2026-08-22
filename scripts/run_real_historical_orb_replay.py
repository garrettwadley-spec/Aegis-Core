"""Replay a real local SPY OHLCV file through the Aegis ORB loop."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from aegis.clock import ClockMode, system_clock
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    PER_BAR_VOLUME,
    REAL_HISTORICAL_FACTOR_ORIGIN,
    REAL_HISTORICAL_LEARNING_ELIGIBILITY,
    SESSION_TIMEZONE,
    SOURCE_TIMEZONE,
    STOOQ_STYLE_PROVIDER,
    STOOQ_STYLE_PROVIDER_CONFIDENCE,
    CanonicalMarketHistory,
    HistoricalBarReplayAdapter,
    InsufficientHistoryError,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    determine_volume_semantics,
    file_sha256,
    load_stooq_style_bars,
    validate_timezone_sessions,
)
from aegis.outcomes import OutcomeJournal, OutcomeObserver
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


DEFAULT_SOURCE = Path.home() / (
    "Downloads/5_us_txt/data/5 min/us/nyse etfs/2/spy.us.txt"
)
DEFAULT_TIMEZONE_SAMPLES = (
    date(2026, 1, 5),
    date(2026, 2, 2),
    date(2026, 3, 9),
    date(2026, 3, 16),
    date(2026, 3, 30),
    date(2026, 4, 6),
)


def _git_head(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _claim_session_once(
    claimed: set[tuple[str, str]],
    symbol: str,
    session: str,
) -> bool:
    key = (symbol, session)
    if key in claimed:
        return False
    claimed.add(key)
    return True


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.6%}"


def _money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"+${value:.4f}" if value >= 0 else f"-${abs(value):.4f}"


def _render_output(manifest: dict[str, Any]) -> str:
    dataset = manifest["dataset"]
    replay = manifest["replay"]
    evidence = manifest["evidence"]
    provenance = manifest["provenance"]
    lines = [
        "DATASET",
        f"Source: {dataset['provider']} ({dataset['provider_confidence']} confidence)",
        f"File: {dataset['file']}",
        f"SHA-256: {dataset['sha256']}",
        f"Symbol: {dataset['source_symbol']}",
        f"Date range: {dataset['date_start']} to {dataset['date_end']}",
        f"Rows: {dataset['rows']}",
        f"Sessions: {dataset['sessions']}",
        f"Raw timezone: {dataset['source_timezone']}",
        f"Normalized timezone: {dataset['session_timezone']}",
        f"Volume semantics: {dataset['volume_semantics']}",
        "",
        "TIMEZONE VALIDATION",
    ]
    for sample in manifest["timezone_validation"]:
        lines.append(
            f"{sample['session']}: raw {sample['raw_open']} -> "
            f"New York {sample['new_york_open']} "
            f"({'PASS' if sample['passed'] else 'FAIL'})"
        )
    lines.extend(
        (
            "",
            "REPLAY",
            f"Observations: {replay['observations']}",
            f"Sessions: {replay['sessions']}",
            f"Sufficient-history sessions: {replay['sufficient_history_sessions']}",
            f"Insufficient-history sessions: {replay['insufficient_history_sessions']}",
            f"Signals: {replay['signals']}",
            f"NO_ACTION sessions: {replay['no_action_sessions']}",
            f"Decisions: {replay['decisions']}",
            f"Outcomes: {replay['outcomes']}",
            "",
            "EVIDENCE",
            f"Profitable: {evidence['profitable']}",
            f"Unprofitable: {evidence['unprofitable']}",
            f"Flat: {evidence['flat']}",
            "Directional accuracy: "
            + (
                "N/A"
                if evidence["directional_accuracy"] is None
                else f"{evidence['directional_accuracy']:.2%}"
            ),
            "Cumulative signed return: "
            + _money(evidence["cumulative_signed_return"]),
            f"Average return %: {_percent(evidence['average_return_pct'])}",
            f"Best: {_percent(evidence['best_return_pct'])}",
            f"Worst: {_percent(evidence['worst_return_pct'])}",
            "",
            "PROVENANCE",
            f"Input origin: {provenance['input_origin']}",
            f"Learning eligibility: {provenance['learning_eligibility']}",
            f"Decision journal: {provenance['decision_journal']}",
            f"Outcome journal: {provenance['outcome_journal']}",
            f"Run manifest: {provenance['run_manifest']}",
        )
    )
    return "\n".join(lines)


def run_replay(
    source_file: Path,
    output_root: Path,
    *,
    repository: Path | None = None,
    code_commit: str | None = None,
    timezone_samples: tuple[date, ...] = DEFAULT_TIMEZONE_SAMPLES,
) -> tuple[dict[str, Any], str]:
    """Run one deterministic, offline, no-lookahead historical replay."""

    repository = repository or Path(__file__).resolve().parents[1]
    commit = code_commit or _git_head(repository)
    source_file = source_file.resolve()
    bars = load_stooq_style_bars(source_file)
    source_hash = file_sha256(source_file)
    volume = determine_volume_semantics(bars)
    if volume.classification != PER_BAR_VOLUME:
        raise ValueError("source volume semantics remain ambiguous")
    timezone_validation = validate_timezone_sessions(bars, timezone_samples)
    if not all(sample.passed for sample in timezone_validation):
        raise ValueError("Europe/Warsaw source timezone validation failed")

    config = OpeningRangeCalculationConfig()
    run_identity = json.dumps(
        {
            "source_sha256": source_hash,
            "code_commit": commit,
            "factor_config": config.to_dict(),
            "strategy": OpeningRangeStrategy.name,
        },
        sort_keys=True,
    )
    run_id = f"LAUNCH008R-{sha256(run_identity.encode()).hexdigest()[:16].upper()}"
    run_directory = output_root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    decision_path = run_directory / "decisions.jsonl"
    outcome_path = run_directory / "outcomes.jsonl"
    manifest_path = run_directory / "manifest.json"

    market_data_bus = MarketDataBus()
    history = CanonicalMarketHistory()
    snapshot_builder = MarketSnapshotBuilder()
    outcome_observer = OutcomeObserver(OutcomeJournal(outcome_path))
    market_data_bus.subscribe(history)
    market_data_bus.subscribe(snapshot_builder)
    market_data_bus.subscribe(outcome_observer)
    calculator = OpeningRangeFactorCalculator(history, config)
    decision_service = PaperDecisionService(DecisionJournal(decision_path))
    adapter = HistoricalBarReplayAdapter(
        bars,
        source_file=source_file,
        source_file_sha256=source_hash,
        code_commit=commit,
        volume_semantics=volume.classification,
    )

    all_sessions = {bar.session_date.isoformat() for bar in bars}
    sufficient_sessions: set[str] = set()
    claimed_sessions: set[tuple[str, str]] = set()
    signals = 0
    decisions = []
    observations = 0
    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time=bars[0].utc_timestamp,
        replay_step_seconds=0.001,
        sequence_start=1,
    )
    try:
        for raw in adapter.observations():
            canonical = market_data_bus.ingest(raw)
            observations += 1
            session = str(canonical.metadata["source_session"])
            session_key = (canonical.symbol, session)
            if session_key in claimed_sessions:
                continue
            current_sequence = history.window(canonical.symbol)[-1].sequence_number
            try:
                factors = calculator.calculate(
                    canonical.symbol,
                    as_of_sequence=current_sequence,
                    input_origin=REAL_HISTORICAL_FACTOR_ORIGIN,
                )
            except InsufficientHistoryError:
                continue
            sufficient_sessions.add(session)
            snapshot = snapshot_builder.build()
            bridge = SnapshotStrategyBridge(
                OpeningRangeStrategy(),
                opening_range_factors={canonical.symbol: factors},
            )
            generated = bridge.evaluate(snapshot)
            if not generated:
                continue
            signals += len(generated)
            if not _claim_session_once(
                claimed_sessions,
                canonical.symbol,
                session,
            ):
                continue
            decision = decision_service.execute(
                generated[0],
                snapshot,
                opening_range_factors=factors,
                learning_eligibility=(
                    REAL_HISTORICAL_LEARNING_ELIGIBILITY
                ),
            )
            if decision is not None:
                decisions.append(decision)
                outcome_observer.observe_decision(decision)
    finally:
        system_clock.set_mode(ClockMode.LIVE)

    outcomes = outcome_observer.outcomes
    returns = [outcome.signed_return_pct for outcome in outcomes]
    directional = [
        outcome.directional_correct
        for outcome in outcomes
        if outcome.directional_correct is not None
    ]
    decision_sessions = {session for _, session in claimed_sessions}
    no_action_sessions = sufficient_sessions - decision_sessions
    insufficient_sessions = all_sessions - sufficient_sessions
    cumulative_return = sum(outcome.signed_return for outcome in outcomes)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "dataset": {
            "provider": STOOQ_STYLE_PROVIDER,
            "provider_confidence": STOOQ_STYLE_PROVIDER_CONFIDENCE,
            "file": str(source_file),
            "sha256": source_hash,
            "source_symbol": bars[0].source_symbol,
            "period_minutes": bars[0].period_minutes,
            "date_start": bars[0].session_date.isoformat(),
            "date_end": bars[-1].session_date.isoformat(),
            "source_timestamp_start": bars[0].raw_timestamp.isoformat(),
            "source_timestamp_end": bars[-1].raw_timestamp.isoformat(),
            "rows": len(bars),
            "sessions": len(all_sessions),
            "source_timezone": SOURCE_TIMEZONE,
            "session_timezone": SESSION_TIMEZONE,
            "volume_semantics": volume.classification,
            "volume_comparisons": volume.within_session_comparisons,
            "volume_decreases": volume.within_session_decreases,
        },
        "lineage": {
            "verified_repository_transformation": [
                str(source_file),
                str((repository / "scripts/combine_data.py").resolve()),
                str((repository / "data/combined_data.csv").resolve()),
            ],
            "replay_input": "direct per-symbol raw file",
            "feature_builder_inspected": str(
                (repository / "build_features.py").resolve()
            ),
        },
        "timezone_validation": [
            {
                "session": sample.session.isoformat(),
                "raw_open": sample.raw_open.isoformat(),
                "raw_close": sample.raw_close.isoformat(),
                "utc_open": sample.utc_open.isoformat(),
                "utc_close": sample.utc_close.isoformat(),
                "new_york_open": sample.new_york_open.isoformat(),
                "new_york_close": sample.new_york_close.isoformat(),
                "passed": sample.passed,
            }
            for sample in timezone_validation
        ],
        "strategy": {
            "name": OpeningRangeStrategy.name,
            "thresholds": {
                "relative_volume_minimum": 4.0,
                "price_change_pct_minimum": 8.0,
                "rsi_maximum_exclusive": 40.0,
                "macd_cross_up_below_zero": True,
            },
            "factor_config": config.to_dict(),
            "maximum_decisions_per_symbol_session": 1,
            "outcome_horizon": "NEXT_CANONICAL_OBSERVATION",
            "no_lookahead": True,
        },
        "replay": {
            "observations": observations,
            "sessions": len(all_sessions),
            "sufficient_history_sessions": len(sufficient_sessions),
            "insufficient_history_sessions": len(insufficient_sessions),
            "signals": signals,
            "no_action_sessions": len(no_action_sessions),
            "decisions": len(decisions),
            "outcomes": len(outcomes),
            "sufficient_session_dates": sorted(sufficient_sessions),
            "insufficient_session_dates": sorted(insufficient_sessions),
            "decision_session_dates": sorted(decision_sessions),
            "no_action_session_dates": sorted(no_action_sessions),
        },
        "evidence": {
            "profitable": sum(outcome.signed_return > 0 for outcome in outcomes),
            "unprofitable": sum(
                outcome.signed_return < 0 for outcome in outcomes
            ),
            "flat": sum(outcome.signed_return == 0 for outcome in outcomes),
            "directional_accuracy": (
                sum(value is True for value in directional) / len(directional)
                if directional
                else None
            ),
            "cumulative_signed_return": cumulative_return,
            "average_return_pct": statistics.fmean(returns) if returns else None,
            "median_return_pct": statistics.median(returns) if returns else None,
            "best_return_pct": max(returns) if returns else None,
            "worst_return_pct": min(returns) if returns else None,
            "classification": (
                REAL_HISTORICAL_LEARNING_ELIGIBILITY
            ),
            "complete_trade_lifecycle": False,
            "live_or_forward": False,
        },
        "provenance": {
            "input_origin": REAL_HISTORICAL_FACTOR_ORIGIN,
            "learning_eligibility": (
                REAL_HISTORICAL_LEARNING_ELIGIBILITY
            ),
            "code_commit": commit,
            "decision_journal": str(decision_path),
            "outcome_journal": str(outcome_path),
            "run_manifest": str(manifest_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = _render_output(manifest)
    return manifest, output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("runs/historical_replay"),
    )
    arguments = parser.parse_args()
    _, output = run_replay(arguments.source, arguments.output_root)
    print(output)


if __name__ == "__main__":
    main()
