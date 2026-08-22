"""Run the fixed LAUNCH-010 ORB gate ablation on real historical data."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import platform
import statistics
import sys
from typing import Any, Iterable, Mapping

from aegis.clock import ClockMode, system_clock
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    PER_BAR_VOLUME,
    CanonicalMarketHistory,
    HistoricalBarReplayAdapter,
    InsufficientHistoryError,
    InvalidMarketHistoryError,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    OpeningRangeFactors,
    load_stooq_style_bars,
)
from aegis.outcomes import OutcomeJournal, OutcomeObserver
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import MarketSignal, OpeningRangeStrategy

from scripts.run_real_universe_orb_scan import (
    DEFAULT_SOURCE_ROOT,
    EVALUATION_END,
    EVALUATION_START,
    EXCLUDED_DIRECTORIES,
    INCLUDED_DIRECTORIES,
    INPUT_ORIGIN,
    STRATEGY_CONDITIONS,
    UniverseFile,
    _factor_condition_results,
    _git_head,
    _selected_bars,
    build_source_manifest,
    discover_equity_universe,
    scan_evaluation_boundaries,
)


DEVELOPMENT_START = date(2026, 1, 5)
DEVELOPMENT_END = date(2026, 3, 13)
HOLDOUT_START = date(2026, 3, 16)
HOLDOUT_END = date(2026, 4, 23)
EXPECTED_SOURCE_AGGREGATE_SHA256 = (
    "44809429EFAF6CC9BF9FDD4C09D93553CBD01A2DD0462F38AE65E39CB489C215"
)
LEARNING_ELIGIBILITY = "RESEARCH_ABLATION_NEXT_OBSERVATION_EVIDENCE"
OUTCOME_HORIZON = "NEXT_CANONICAL_OBSERVATION"
WINDOWS = ("DEVELOPMENT", "HOLDOUT")


@dataclass(frozen=True)
class VariantDefinition:
    variant_id: str
    name: str
    required_conditions: tuple[str, ...]
    advisory_condition: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "name": self.name,
            "required_conditions": list(self.required_conditions),
            "advisory_condition": self.advisory_condition,
        }


VARIANTS = (
    VariantDefinition(
        "V0",
        "BASELINE",
        tuple(STRATEGY_CONDITIONS),
        None,
    ),
    VariantDefinition(
        "V1",
        "MACD_ADVISORY",
        ("relative_volume", "price_change", "rsi"),
        "macd_cross",
    ),
    VariantDefinition(
        "V2",
        "RSI_ADVISORY",
        ("relative_volume", "price_change", "macd_cross"),
        "rsi",
    ),
    VariantDefinition(
        "V3",
        "PRICE_CHANGE_ADVISORY",
        ("relative_volume", "rsi", "macd_cross"),
        "price_change",
    ),
    VariantDefinition(
        "V4",
        "RELATIVE_VOLUME_ADVISORY",
        ("price_change", "rsi", "macd_cross"),
        "relative_volume",
    ),
)


class ResearchDecisionJournal(DecisionJournal):
    """Add fixed ablation context before an isolated decision is persisted."""

    def __init__(self, path: Path, variant_id: str) -> None:
        super().__init__(path)
        self.variant_id = variant_id
        self._context: dict[str, Any] | None = None

    def set_context(
        self,
        *,
        window: str,
        session_date: str,
        evaluation_timestamp: datetime,
        condition_results: Mapping[str, bool],
    ) -> None:
        self._context = {
            "variant_id": self.variant_id,
            "window": window,
            "session_date": session_date,
            "evaluation_timestamp": evaluation_timestamp.astimezone(
                timezone.utc
            ).isoformat(),
            "baseline_condition_passes": {
                name: bool(condition_results[name])
                for name in STRATEGY_CONDITIONS
            },
        }

    def append(self, record: dict[str, Any]) -> Path:
        if self._context is None:
            raise ValueError("research decision context is required")
        record.update(self._context)
        self._context = None
        return super().append(record)


@dataclass
class VariantRuntime:
    definition: VariantDefinition
    decision_journal: ResearchDecisionJournal
    outcome_journal: OutcomeJournal
    decision_service: PaperDecisionService
    observer: OutcomeObserver


def window_for_session(session: date | str) -> str:
    value = date.fromisoformat(session) if isinstance(session, str) else session
    if DEVELOPMENT_START <= value <= DEVELOPMENT_END:
        return "DEVELOPMENT"
    if HOLDOUT_START <= value <= HOLDOUT_END:
        return "HOLDOUT"
    raise ValueError(f"session {value} is outside the predeclared windows")


def variant_matches(
    variant: VariantDefinition,
    condition_results: Mapping[str, bool],
) -> bool:
    return all(condition_results[name] for name in variant.required_conditions)


def matching_variants(
    condition_results: Mapping[str, bool],
) -> tuple[VariantDefinition, ...]:
    return tuple(
        variant
        for variant in VARIANTS
        if variant_matches(variant, condition_results)
    )


def claim_variant_session_once(
    claimed: set[tuple[str, str, str]],
    variant_id: str,
    symbol: str,
    session: str,
) -> bool:
    key = (variant_id, symbol, session)
    if key in claimed:
        return False
    claimed.add(key)
    return True


def validate_no_lookahead(
    factors: OpeningRangeFactors,
    current_sequence: int,
) -> None:
    if max(factors.source_event_sequences) > current_sequence:
        raise ValueError("factor provenance contains a future event")


def pattern_key(condition_results: Mapping[str, bool]) -> str:
    return "".join(
        "1" if condition_results[name] else "0"
        for name in STRATEGY_CONDITIONS
    )


def new_joint_pattern_table() -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for values in product((False, True), repeat=len(STRATEGY_CONDITIONS)):
        conditions = dict(zip(STRATEGY_CONDITIONS, values))
        key = pattern_key(conditions)
        table[key] = {
            "pattern": key,
            "conditions": conditions,
            "count": 0,
            "development_count": 0,
            "holdout_count": 0,
            "percentage_of_sufficient_history_points": 0.0,
        }
    return table


def record_joint_pattern(
    table: dict[str, dict[str, Any]],
    condition_results: Mapping[str, bool],
    window: str,
) -> None:
    entry = table[pattern_key(condition_results)]
    entry["count"] += 1
    entry[f"{window.lower()}_count"] += 1


def finalize_joint_pattern_table(
    table: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    total = sum(entry["count"] for entry in table.values())
    for entry in table.values():
        entry["percentage_of_sufficient_history_points"] = (
            entry["count"] / total if total else 0.0
        )
    return [table[key] for key in sorted(table)]


_INTERSECTION_PATTERNS = {
    "baseline": "1111",
    "no_macd": "1110",
    "no_rsi": "1101",
    "no_price_change": "1011",
    "no_relative_volume": "0111",
}


def leave_one_out_intersections(
    table: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    return {
        name: {
            "count": int(table[key]["count"]),
            "development_count": int(table[key]["development_count"]),
            "holdout_count": int(table[key]["holdout_count"]),
        }
        for name, key in _INTERSECTION_PATTERNS.items()
    }


def sample_adequacy(signal_count: int, window: str) -> str:
    minimum = 20 if window == "DEVELOPMENT" else 5
    return "ADEQUATE FOR REVIEW" if signal_count >= minimum else "INSUFFICIENT"


def _research_signal(
    variant: VariantDefinition,
    factors: OpeningRangeFactors,
    condition_results: Mapping[str, bool],
) -> MarketSignal:
    if not variant_matches(variant, condition_results):
        raise ValueError(f"{variant.variant_id} does not match the factor state")
    if variant.variant_id == "V0":
        signal = OpeningRangeStrategy().evaluate(
            {
                "symbol": factors.symbol,
                "relative_volume": factors.relative_volume,
                "price_change_pct": factors.price_change_pct,
                "rsi": factors.rsi,
                "macd_cross": factors.macd_cross_up_below_zero,
            }
        )
        if signal is None:
            raise ValueError("production baseline rejected a matching V0 state")
        return signal
    return MarketSignal(
        symbol=factors.symbol,
        action="BUY",
        confidence=0.92,
        strategy=f"{OpeningRangeStrategy.name} Research {variant.variant_id}",
        quantity=1,
    )


def _create_variant_runtimes(run_directory: Path) -> dict[str, VariantRuntime]:
    runtimes: dict[str, VariantRuntime] = {}
    for definition in VARIANTS:
        variant_directory = run_directory / "variant_journals" / definition.variant_id
        decision_journal = ResearchDecisionJournal(
            variant_directory / "decisions.jsonl",
            definition.variant_id,
        )
        outcome_journal = OutcomeJournal(variant_directory / "outcomes.jsonl")
        runtimes[definition.variant_id] = VariantRuntime(
            definition=definition,
            decision_journal=decision_journal,
            outcome_journal=outcome_journal,
            decision_service=PaperDecisionService(decision_journal, quantity=1),
            observer=OutcomeObserver(outcome_journal),
        )
    return runtimes


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as destination:
        for value in values:
            destination.write(json.dumps(value, sort_keys=True) + "\n")


def _process_symbol(
    *,
    item: UniverseFile,
    content_hash: str,
    code_commit: str,
    factor_config: OpeningRangeCalculationConfig,
    runtimes: Mapping[str, VariantRuntime],
    joint_patterns: dict[str, dict[str, Any]],
    evaluation_counts: dict[str, int],
    claimed_sessions: set[tuple[str, str, str]],
) -> dict[str, int]:
    boundary_scan = scan_evaluation_boundaries(item)
    if not boundary_scan.eligible_rows:
        return {
            "sessions": boundary_scan.sessions,
            "evaluation_points": boundary_scan.evaluation_points,
            "sufficient_factor_points": 0,
            "insufficient_history_points": 0,
            "invalid_market_history_points": 0,
        }

    bars = _selected_bars(load_stooq_style_bars(item.path))
    if not bars:
        raise ValueError("eligible source has no selected replay bars")
    adapter = HistoricalBarReplayAdapter(
        bars,
        source_file=item.path,
        source_file_sha256=content_hash,
        code_commit=code_commit,
        volume_semantics=PER_BAR_VOLUME,
    )
    market_data_bus = MarketDataBus()
    history = CanonicalMarketHistory(max_observations_per_symbol=1_000)
    snapshot_builder = MarketSnapshotBuilder()
    market_data_bus.subscribe(history)
    market_data_bus.subscribe(snapshot_builder)
    for runtime in runtimes.values():
        market_data_bus.subscribe(runtime.observer)
    calculator = OpeningRangeFactorCalculator(history, factor_config)
    sufficient = 0
    insufficient = 0
    invalid = 0

    for observation in adapter.observations():
        canonical = market_data_bus.ingest(observation)
        row_identifier = str(canonical.metadata["source_row_identifier"])
        completed_at = boundary_scan.eligible_rows.get(row_identifier)
        if completed_at is None:
            continue
        current_sequence = history.window(canonical.symbol)[-1].sequence_number
        try:
            factors = calculator.calculate(
                canonical.symbol,
                as_of_sequence=current_sequence,
                input_origin=INPUT_ORIGIN,
            )
        except InsufficientHistoryError:
            insufficient += 1
            continue
        except InvalidMarketHistoryError:
            invalid += 1
            continue
        validate_no_lookahead(factors, current_sequence)
        sufficient += 1
        session = str(canonical.metadata["source_session"])
        window = window_for_session(session)
        evaluation_counts[window] += 1
        condition_results = _factor_condition_results(factors)
        record_joint_pattern(joint_patterns, condition_results, window)
        matches = matching_variants(condition_results)
        if not matches:
            continue
        snapshot = snapshot_builder.build()
        for definition in matches:
            if not claim_variant_session_once(
                claimed_sessions,
                definition.variant_id,
                canonical.symbol,
                session,
            ):
                continue
            signal = _research_signal(definition, factors, condition_results)
            runtime = runtimes[definition.variant_id]
            runtime.decision_journal.set_context(
                window=window,
                session_date=session,
                evaluation_timestamp=completed_at,
                condition_results=condition_results,
            )
            decision = runtime.decision_service.execute(
                signal,
                snapshot,
                opening_range_factors=factors,
                learning_eligibility=LEARNING_ELIGIBILITY,
            )
            if decision is None:
                raise ValueError("matching research signal produced no decision")
            runtime.observer.observe_decision(decision)

    return {
        "sessions": boundary_scan.sessions,
        "evaluation_points": boundary_scan.evaluation_points,
        "sufficient_factor_points": sufficient,
        "insufficient_history_points": insufficient,
        "invalid_market_history_points": invalid,
    }


def _aggregate_journals(
    runtimes: Mapping[str, VariantRuntime],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for definition in VARIANTS:
        runtime = runtimes[definition.variant_id]
        decisions = _read_jsonl(runtime.decision_journal.path)
        decision_by_id = {
            record["decision_record_id"]: record for record in decisions
        }
        signals.extend(decisions)
        for outcome in runtime.outcome_journal.records():
            decision = decision_by_id[outcome["decision_record_id"]]
            enriched = dict(outcome)
            for key in (
                "variant_id",
                "window",
                "session_date",
                "evaluation_timestamp",
                "baseline_condition_passes",
            ):
                enriched[key] = decision[key]
            outcomes.append(enriched)

    def sort_key(record: Mapping[str, Any]) -> tuple[str, ...]:
        return (
            str(record["symbol"]),
            str(record["session_date"]),
            str(record["evaluation_timestamp"]),
            str(record["variant_id"]),
        )

    signals.sort(key=sort_key)
    outcomes.sort(key=sort_key)
    return signals, outcomes


def summarize_variant(
    definition: VariantDefinition,
    window: str,
    evaluation_points: int,
    signals: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_signals = [
        record
        for record in signals
        if record["variant_id"] == definition.variant_id
        and (window == "COMBINED" or record["window"] == window)
    ]
    selected_outcomes = [
        record
        for record in outcomes
        if record["variant_id"] == definition.variant_id
        and (window == "COMBINED" or record["window"] == window)
    ]
    signed_returns = [float(record["signed_return"]) for record in selected_outcomes]
    returns_pct = [
        float(record["signed_return_pct"]) for record in selected_outcomes
    ]
    directional = [
        record["directional_correct"]
        for record in selected_outcomes
        if record["directional_correct"] is not None
    ]
    signal_count = len(selected_signals)
    result = {
        "variant_id": definition.variant_id,
        "variant_name": definition.name,
        "window": window,
        "evaluation_points": evaluation_points,
        "signals": signal_count,
        "paper_decisions": signal_count,
        "symbols_with_signals": len(
            {record["symbol"] for record in selected_signals}
        ),
        "sessions_with_signals": len(
            {
                (record["symbol"], record["session_date"])
                for record in selected_signals
            }
        ),
        "outcomes": len(selected_outcomes),
        "profitable": sum(value > 0 for value in signed_returns),
        "unprofitable": sum(value < 0 for value in signed_returns),
        "flat": sum(value == 0 for value in signed_returns),
        "directional_accuracy": (
            sum(value is True for value in directional) / len(directional)
            if directional
            else None
        ),
        "cumulative_signed_one_share_return": sum(signed_returns),
        "average_return_pct": (
            statistics.fmean(returns_pct) if returns_pct else None
        ),
        "median_return_pct": (
            statistics.median(returns_pct) if returns_pct else None
        ),
        "best_outcome_pct": max(returns_pct) if returns_pct else None,
        "worst_outcome_pct": min(returns_pct) if returns_pct else None,
        "evidence_classification": LEARNING_ELIGIBILITY,
    }
    if window in WINDOWS:
        result["sample_adequacy"] = sample_adequacy(signal_count, window)
    return result


def build_diagnosis(
    combined: Mapping[str, Mapping[str, Any]],
    development: Mapping[str, Mapping[str, Any]],
    holdout: Mapping[str, Mapping[str, Any]],
    intersections: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    baseline_operational = int(combined["V0"]["signals"]) > 0
    largest_count = max(int(result["signals"]) for result in combined.values())
    largest_variants = sorted(
        variant_id
        for variant_id, result in combined.items()
        if int(result["signals"]) == largest_count
    )
    leave_one_out = {
        name: int(intersections[name]["count"])
        for name in (
            "no_macd",
            "no_rsi",
            "no_price_change",
            "no_relative_volume",
        )
    }
    largest_intersection_count = max(leave_one_out.values())
    largest_intersections = sorted(
        name for name, count in leave_one_out.items()
        if count == largest_intersection_count
    )
    if largest_intersections == ["no_macd"] and largest_intersection_count > 0:
        incompatibility_diagnosis = (
            "MACD is the uniquely largest exact leave-one-out incompatibility."
        )
    elif "no_macd" in largest_intersections and largest_intersection_count > 0:
        incompatibility_diagnosis = (
            "MACD is tied with another exact leave-one-out incompatibility."
        )
    elif largest_intersection_count > 0:
        incompatibility_diagnosis = (
            "A non-MACD conjunction has the largest exact leave-one-out count."
        )
    else:
        incompatibility_diagnosis = (
            "No exact leave-one-out intersection generated an observation."
        )
    both_windows = {
        variant_id: (
            int(development[variant_id]["signals"]) > 0
            and int(holdout[variant_id]["signals"]) > 0
        )
        for variant_id in combined
    }
    observed_above_half = {
        window: {
            variant_id: (
                result["directional_accuracy"] is not None
                and float(result["directional_accuracy"]) > 0.5
            )
            for variant_id, result in results.items()
        }
        for window, results in (
            ("DEVELOPMENT", development),
            ("HOLDOUT", holdout),
        )
    }
    controlled_validation_candidates = sorted(
        variant_id
        for variant_id in combined
        if development[variant_id]["sample_adequacy"] == "ADEQUATE FOR REVIEW"
        and holdout[variant_id]["sample_adequacy"] == "ADEQUATE FOR REVIEW"
    )
    return {
        "baseline_operational": baseline_operational,
        "largest_signal_population": {
            "variant_ids": largest_variants,
            "signals": largest_count,
        },
        "largest_leave_one_out_intersection": {
            "intersections": largest_intersections,
            "count": largest_intersection_count,
            "all_counts": leave_one_out,
        },
        "gate_incompatibility_diagnosis": incompatibility_diagnosis,
        "signals_in_both_windows": both_windows,
        "observed_directional_accuracy_above_50_percent": observed_above_half,
        "controlled_validation_candidates_by_sample_count": (
            controlled_validation_candidates
        ),
        "profitability_claim_justified": False,
        "production_strategy_changed": False,
        "thresholds_changed": False,
    }


def compute_run_id(
    *,
    source_manifest_hash: str,
    code_commit: str,
    factor_config: Mapping[str, Any],
    maximum_files: int | None,
) -> str:
    identity = json.dumps(
        {
            "source_manifest_hash": source_manifest_hash,
            "code_commit": code_commit,
            "development": [DEVELOPMENT_START.isoformat(), DEVELOPMENT_END.isoformat()],
            "holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            "variants": [variant.to_dict() for variant in VARIANTS],
            "factor_config": factor_config,
            "maximum_files": maximum_files,
        },
        sort_keys=True,
    )
    return f"LAUNCH010-{sha256(identity.encode()).hexdigest()[:16].upper()}"


def _metric(value: float | None, *, percent: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.4%}" if percent else f"{value:.4f}"


def _result_line(result: Mapping[str, Any]) -> str:
    accuracy = (
        "N/A"
        if result["directional_accuracy"] is None
        else f"{float(result['directional_accuracy']):.2%}"
    )
    return (
        f"{result['variant_id']}: eval={result['evaluation_points']} "
        f"signals={result['signals']} symbols={result['symbols_with_signals']} "
        f"sessions={result['sessions_with_signals']} outcomes={result['outcomes']} "
        f"P/U/F={result['profitable']}/{result['unprofitable']}/{result['flat']} "
        f"accuracy={accuracy} "
        f"signed_return={float(result['cumulative_signed_one_share_return']):+.4f} "
        f"avg={_metric(result['average_return_pct'], percent=True)} "
        f"median={_metric(result['median_return_pct'], percent=True)} "
        f"best={_metric(result['best_outcome_pct'], percent=True)} "
        f"worst={_metric(result['worst_outcome_pct'], percent=True)}"
    )


def render_output(summary: Mapping[str, Any]) -> str:
    manifest = summary["manifest"]
    patterns = summary["joint_condition_patterns"]
    intersections = patterns["leave_one_out_intersections"]
    diagnosis = summary["diagnosis"]
    lines = [
        "EXPERIMENT",
        "Universe: " + ", ".join(manifest["universe_rules"]["included"]),
        "Excluded: " + ", ".join(manifest["universe_rules"]["excluded"]),
        f"Symbols processed: {manifest['runtime']['symbols_processed']}",
        f"Development: {DEVELOPMENT_START} to {DEVELOPMENT_END}",
        f"Holdout: {HOLDOUT_START} to {HOLDOUT_END}",
        "Thresholds unchanged: YES",
        "Variants: " + ", ".join(
            f"{variant.variant_id} {variant.name}" for variant in VARIANTS
        ),
        "",
        "JOINT CONDITION PATTERNS",
        "Pattern order: relative_volume, price_change, rsi, macd_cross",
    ]
    for entry in patterns["patterns"]:
        lines.append(
            f"{entry['pattern']}: count={entry['count']} "
            f"development={entry['development_count']} "
            f"holdout={entry['holdout_count']} "
            f"pct={entry['percentage_of_sufficient_history_points']:.6%}"
        )
    lines.extend(("", "LEAVE-ONE-OUT INTERSECTIONS"))
    for name in (
        "baseline",
        "no_macd",
        "no_rsi",
        "no_price_change",
        "no_relative_volume",
    ):
        value = intersections[name]
        lines.append(
            f"{name}: count={value['count']} "
            f"development={value['development_count']} "
            f"holdout={value['holdout_count']}"
        )
    lines.extend(("", "VARIANT RESULTS - DEVELOPMENT"))
    for variant in VARIANTS:
        lines.append(_result_line(summary["development_results"][variant.variant_id]))
    lines.extend(("", "VARIANT RESULTS - HOLDOUT"))
    for variant in VARIANTS:
        lines.append(_result_line(summary["holdout_results"][variant.variant_id]))
    lines.extend(("", "SAMPLE ADEQUACY"))
    for variant in VARIANTS:
        variant_id = variant.variant_id
        lines.append(
            f"{variant_id}: development="
            f"{summary['development_results'][variant_id]['sample_adequacy']}; "
            f"holdout={summary['holdout_results'][variant_id]['sample_adequacy']}"
        )
    lines.extend(
        (
            "",
            "DIAGNOSIS",
            "Baseline operational: "
            + ("YES" if diagnosis["baseline_operational"] else "NO"),
            "Largest signal population: "
            + ", ".join(diagnosis["largest_signal_population"]["variant_ids"])
            + f" ({diagnosis['largest_signal_population']['signals']})",
            "Largest exact leave-one-out intersection: "
            + ", ".join(
                diagnosis["largest_leave_one_out_intersection"]["intersections"]
            )
            + f" ({diagnosis['largest_leave_one_out_intersection']['count']})",
            "Gate incompatibility: "
            + diagnosis["gate_incompatibility_diagnosis"],
            "Signals in both windows: "
            + ", ".join(
                f"{variant.variant_id}="
                + (
                    "YES"
                    if diagnosis["signals_in_both_windows"][variant.variant_id]
                    else "NO"
                )
                for variant in VARIANTS
            ),
            "Observed directional accuracy above 50% - development: "
            + (
                ", ".join(
                    variant_id
                    for variant_id, passed in diagnosis[
                        "observed_directional_accuracy_above_50_percent"
                    ]["DEVELOPMENT"].items()
                    if passed
                )
                or "None"
            ),
            "Observed directional accuracy above 50% - holdout: "
            + (
                ", ".join(
                    variant_id
                    for variant_id, passed in diagnosis[
                        "observed_directional_accuracy_above_50_percent"
                    ]["HOLDOUT"].items()
                    if passed
                )
                or "None"
            ),
            "Controlled-validation candidates by sample count: "
            + (
                ", ".join(
                    diagnosis[
                        "controlled_validation_candidates_by_sample_count"
                    ]
                )
                or "None"
            ),
            "Profitability claim justified: NO",
        )
    )
    if not diagnosis["baseline_operational"]:
        lines.extend(
            (
                "",
                "BASELINE REMAINS NON-OPERATIONAL IN THE APPROVED UNIVERSE "
                "AND PERIOD.",
            )
        )
    return "\n".join(lines)


def run_ablation(
    source_root: Path,
    output_root: Path,
    *,
    repository: Path | None = None,
    code_commit: str | None = None,
    maximum_files: int | None = None,
) -> tuple[dict[str, Any], str]:
    if maximum_files is not None and maximum_files <= 0:
        raise ValueError("maximum_files must be positive")
    repository = repository or Path(__file__).resolve().parents[1]
    commit = code_commit or _git_head(repository)
    runtime_started = system_clock.now()
    monotonic_started = system_clock.monotonic()
    inventory = discover_equity_universe(source_root)
    selected_files = (
        inventory.files[:maximum_files]
        if maximum_files is not None
        else inventory.files
    )
    source_hashes, aggregate_hash, hash_errors = build_source_manifest(selected_files)
    production_source = (
        maximum_files is None
        and source_root.resolve() == DEFAULT_SOURCE_ROOT.resolve()
    )
    if production_source and aggregate_hash != EXPECTED_SOURCE_AGGREGATE_SHA256:
        raise ValueError("source aggregate SHA-256 differs from LAUNCH-009")
    factor_config = OpeningRangeCalculationConfig()
    run_id = compute_run_id(
        source_manifest_hash=aggregate_hash,
        code_commit=commit,
        factor_config=factor_config.to_dict(),
        maximum_files=maximum_files,
    )
    run_directory = output_root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    runtimes = _create_variant_runtimes(run_directory)
    joint_patterns = new_joint_pattern_table()
    evaluation_counts = {window: 0 for window in WINDOWS}
    claimed_sessions: set[tuple[str, str, str]] = set()
    errors = list(hash_errors)
    processing = {
        "symbols_processed": 0,
        "sessions_processed": 0,
        "ten_minute_evaluation_points": 0,
        "sufficient_history_points": 0,
        "insufficient_history_points": 0,
        "invalid_market_history_points": 0,
    }

    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2025-12-01T14:30:00+00:00",
        replay_step_seconds=0.001,
        sequence_start=1,
    )
    try:
        for item in selected_files:
            content_hash = source_hashes.get(item.relative_path)
            if content_hash is None:
                continue
            try:
                result = _process_symbol(
                    item=item,
                    content_hash=content_hash,
                    code_commit=commit,
                    factor_config=factor_config,
                    runtimes=runtimes,
                    joint_patterns=joint_patterns,
                    evaluation_counts=evaluation_counts,
                    claimed_sessions=claimed_sessions,
                )
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append({"file": item.relative_path, "error": str(exc)})
                continue
            processing["symbols_processed"] += 1
            processing["sessions_processed"] += result["sessions"]
            processing["ten_minute_evaluation_points"] += result[
                "evaluation_points"
            ]
            processing["sufficient_history_points"] += result[
                "sufficient_factor_points"
            ]
            processing["insufficient_history_points"] += result[
                "insufficient_history_points"
            ]
            processing["invalid_market_history_points"] += result[
                "invalid_market_history_points"
            ]
    finally:
        system_clock.set_mode(ClockMode.LIVE)

    runtime_ended = system_clock.now()
    processing.update(
        {
            "runtime_started": runtime_started.isoformat(),
            "runtime_ended": runtime_ended.isoformat(),
            "runtime_seconds": system_clock.monotonic() - monotonic_started,
        }
    )
    signals, outcomes = _aggregate_journals(runtimes)
    patterns = finalize_joint_pattern_table(joint_patterns)
    intersections = leave_one_out_intersections(joint_patterns)
    combined_evaluations = sum(evaluation_counts.values())
    development_results = {
        variant.variant_id: summarize_variant(
            variant,
            "DEVELOPMENT",
            evaluation_counts["DEVELOPMENT"],
            signals,
            outcomes,
        )
        for variant in VARIANTS
    }
    holdout_results = {
        variant.variant_id: summarize_variant(
            variant,
            "HOLDOUT",
            evaluation_counts["HOLDOUT"],
            signals,
            outcomes,
        )
        for variant in VARIANTS
    }
    combined_results = {
        variant.variant_id: summarize_variant(
            variant,
            "COMBINED",
            combined_evaluations,
            signals,
            outcomes,
        )
        for variant in VARIANTS
    }
    diagnosis = build_diagnosis(
        combined_results,
        development_results,
        holdout_results,
        intersections,
    )
    joint_condition_artifact = {
        "condition_order": list(STRATEGY_CONDITIONS),
        "sufficient_history_points": combined_evaluations,
        "development_points": evaluation_counts["DEVELOPMENT"],
        "holdout_points": evaluation_counts["HOLDOUT"],
        "patterns": patterns,
        "leave_one_out_intersections": intersections,
    }
    manifest = {
        "run_id": run_id,
        "code_commit": commit,
        "research_only": True,
        "source_root": str(source_root.resolve()),
        "source_file_count": len(selected_files),
        "source_aggregate_sha256": aggregate_hash,
        "expected_source_aggregate_sha256": EXPECTED_SOURCE_AGGREGATE_SHA256,
        "universe_rules": {
            "included": list(INCLUDED_DIRECTORIES),
            "excluded": list(EXCLUDED_DIRECTORIES),
            "duplicate_handling": (
                "lexicographically first source path retained per symbol"
            ),
        },
        "date_windows": {
            "overall": [EVALUATION_START.isoformat(), EVALUATION_END.isoformat()],
            "development": [
                DEVELOPMENT_START.isoformat(),
                DEVELOPMENT_END.isoformat(),
            ],
            "holdout": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
            "earlier_sessions_used_for_lookback_only": True,
        },
        "unchanged_thresholds": {
            "price_minimum_inclusive": 2.50,
            "price_maximum_inclusive": 8.00,
            "cumulative_session_volume_minimum_exclusive": 1_000_000,
            "relative_volume_minimum_inclusive": 4.0,
            "price_change_pct_minimum_inclusive": 8.0,
            "rsi_maximum_exclusive": 40.0,
            "macd_upward_cross_below_zero": True,
        },
        "variants": [variant.to_dict() for variant in VARIANTS],
        "factor_configuration": factor_config.to_dict(),
        "outcome_horizon": OUTCOME_HORIZON,
        "input_origin": INPUT_ORIGIN,
        "learning_eligibility": LEARNING_ELIGIBILITY,
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "version": platform.python_version(),
        },
        "processing_order": (
            "deterministic symbol/source path, then chronological observation, "
            "then V0 through V4"
        ),
        "runtime": processing,
        "errors_and_skipped_files": errors,
        "production_strategy_changed": False,
        "thresholds_changed": False,
    }
    _write_json(run_directory / "manifest.json", manifest)
    _write_json(
        run_directory / "joint_condition_patterns.json",
        joint_condition_artifact,
    )
    _write_json(run_directory / "variant_summary.json", combined_results)
    _write_json(run_directory / "development_results.json", development_results)
    _write_json(run_directory / "holdout_results.json", holdout_results)
    _write_jsonl(run_directory / "signals.jsonl", signals)
    _write_jsonl(run_directory / "outcomes.jsonl", outcomes)
    _write_json(run_directory / "diagnosis.json", diagnosis)
    summary = {
        "manifest": manifest,
        "joint_condition_patterns": joint_condition_artifact,
        "variant_summary": combined_results,
        "development_results": development_results,
        "holdout_results": holdout_results,
        "diagnosis": diagnosis,
        "artifact_directory": str(run_directory),
    }
    return summary, render_output(summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("runs/orb_gate_ablation"),
    )
    parser.add_argument("--maximum-files", type=int)
    arguments = parser.parse_args()
    _, output = run_ablation(
        arguments.source_root,
        arguments.output_root,
        maximum_files=arguments.maximum_files,
    )
    print(output)


if __name__ == "__main__":
    main()
