"""Evaluate the unchanged ORB strategy across the local U.S. stock archive."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
from math import isfinite
import platform
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from aegis.clock import ClockMode, system_clock
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    PER_BAR_VOLUME,
    CanonicalMarketHistory,
    HistoricalBar,
    HistoricalBarReplayAdapter,
    InsufficientHistoryError,
    InvalidMarketHistoryError,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    OpeningRangeFactors,
    RawMarketData,
    file_sha256,
    load_stooq_style_bars,
)
from aegis.outcomes import OutcomeJournal, OutcomeObserver
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


EVALUATION_START = date(2026, 1, 5)
EVALUATION_END = date(2026, 4, 23)
INCLUDED_DIRECTORIES = (
    "nasdaq stocks",
    "nyse stocks",
    "nysemkt stocks",
)
EXCLUDED_DIRECTORIES = (
    "nasdaq etfs",
    "nyse etfs",
    "nysemkt etfs",
)
CONDITION_ORDER = (
    "valid_regular_session_observation",
    "price_range",
    "cumulative_session_volume",
    "sufficient_factor_history",
    "relative_volume",
    "price_change",
    "rsi",
    "macd_cross",
    "complete_actionable_signal",
)
STRATEGY_CONDITIONS = (
    "relative_volume",
    "price_change",
    "rsi",
    "macd_cross",
)
INPUT_ORIGIN = (
    "REAL_HISTORICAL_UNIVERSE_REPLAY_WITH_MARKET_DERIVED_FACTORS"
)
LEARNING_ELIGIBILITY = (
    "REAL_HISTORICAL_UNIVERSE_NEXT_OBSERVATION_EVIDENCE"
)
DEFAULT_SOURCE_ROOT = (
    Path.home() / "Downloads/5_us_txt/data/5 min/us"
)


@dataclass(frozen=True)
class UniverseFile:
    symbol: str
    path: Path
    relative_path: str


@dataclass(frozen=True)
class UniverseInventory:
    files: tuple[UniverseFile, ...]
    included_directories: tuple[str, ...]
    excluded_directories: tuple[str, ...]
    archive_file_count: int
    excluded_file_count: int
    duplicate_symbol_count: int
    duplicate_files_skipped: tuple[str, ...]


@dataclass(frozen=True)
class BoundaryScan:
    sessions: int
    evaluation_points: int
    eligible_rows: dict[str, datetime]
    independent_counts: dict[str, int]
    funnel_counts: dict[str, int]


_SOURCE_HEADER = (
    "TICKER",
    "PER",
    "DATE",
    "TIME",
    "OPEN",
    "HIGH",
    "LOW",
    "CLOSE",
    "VOL",
    "OPENINT",
)
_SOURCE_ZONE = ZoneInfo("Europe/Warsaw")
_SESSION_ZONE = ZoneInfo("America/New_York")


def _symbol_from_path(path: Path) -> str:
    name = path.name.lower()
    return name[:-7].upper() if name.endswith(".us.txt") else path.stem.upper()


def discover_equity_universe(source_root: Path) -> UniverseInventory:
    """Select stock-labeled source directories without symbol heuristics."""

    source_root = source_root.resolve()
    archive_files = tuple(
        sorted(
            source_root.rglob("*.txt"),
            key=lambda path: path.relative_to(source_root).as_posix().lower(),
        )
    )
    included_candidates: list[UniverseFile] = []
    for directory_name in INCLUDED_DIRECTORIES:
        directory = source_root / directory_name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.txt"):
            included_candidates.append(
                UniverseFile(
                    symbol=_symbol_from_path(path),
                    path=path.resolve(),
                    relative_path=path.relative_to(source_root).as_posix(),
                )
            )
    included_candidates.sort(
        key=lambda item: (item.symbol, item.relative_path.lower())
    )

    selected: list[UniverseFile] = []
    duplicate_files: list[str] = []
    seen_symbols: set[str] = set()
    duplicate_symbols: set[str] = set()
    for item in included_candidates:
        if item.symbol in seen_symbols:
            duplicate_symbols.add(item.symbol)
            duplicate_files.append(item.relative_path)
            continue
        seen_symbols.add(item.symbol)
        selected.append(item)

    excluded_count = 0
    for directory_name in EXCLUDED_DIRECTORIES:
        directory = source_root / directory_name
        if directory.is_dir():
            excluded_count += sum(1 for _ in directory.rglob("*.txt"))
    return UniverseInventory(
        files=tuple(selected),
        included_directories=INCLUDED_DIRECTORIES,
        excluded_directories=EXCLUDED_DIRECTORIES,
        archive_file_count=len(archive_files),
        excluded_file_count=excluded_count,
        duplicate_symbol_count=len(duplicate_symbols),
        duplicate_files_skipped=tuple(duplicate_files),
    )


def build_source_manifest(
    files: tuple[UniverseFile, ...],
) -> tuple[dict[str, str], str, list[dict[str, str]]]:
    """Hash selected files and derive one deterministic aggregate hash."""

    hashes: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    digest = sha256()
    for item in files:
        try:
            content_hash = file_sha256(item.path)
        except OSError as exc:
            errors.append(
                {"file": item.relative_path, "error": f"hash error: {exc}"}
            )
            continue
        hashes[item.relative_path] = content_hash
        digest.update(item.relative_path.lower().encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return hashes, digest.hexdigest().upper(), errors


def is_completed_ten_minute_boundary(
    observation: RawMarketData,
) -> tuple[bool, datetime]:
    """Treat a five-minute source timestamp as the bar's opening time."""

    local = datetime.fromisoformat(
        str(observation.metadata["normalized_new_york_timestamp"])
    )
    period_minutes = int(observation.metadata["source_period_minutes"])
    completed_at = local + timedelta(minutes=period_minutes)
    session_open = datetime.combine(local.date(), time(9, 30), local.tzinfo)
    session_close = datetime.combine(local.date(), time(16, 0), local.tzinfo)
    if local < session_open or completed_at > session_close:
        return False, completed_at
    elapsed_minutes = int((completed_at - session_open).total_seconds() // 60)
    return (
        elapsed_minutes > 0 and elapsed_minutes % 10 == 0,
        completed_at,
    )


@lru_cache(maxsize=16_384)
def _normalized_source_time(date_text: str, time_text: str) -> datetime:
    if len(date_text) != 8 or len(time_text) > 6:
        raise ValueError("invalid source date or time width")
    padded_time = time_text.zfill(6)
    if not date_text.isdigit() or not padded_time.isdigit():
        raise ValueError("source date and time must be numeric")
    source_time = datetime(
        int(date_text[:4]),
        int(date_text[4:6]),
        int(date_text[6:8]),
        int(padded_time[:2]),
        int(padded_time[2:4]),
        int(padded_time[4:6]),
        tzinfo=_SOURCE_ZONE,
    )
    return source_time.astimezone(_SESSION_ZONE)


def _number(value: str, field_name: str, source_line: int) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(
            f"line {source_line}: {field_name} must be numeric"
        ) from exc
    if not isfinite(result):
        raise ValueError(f"line {source_line}: {field_name} must be finite")
    return result


def scan_evaluation_boundaries(item: UniverseFile) -> BoundaryScan:
    """Stream fixed-period universe gates before canonical factor work."""

    independent = _empty_counts(
        (
            "valid_regular_session_observation",
            "price_range",
            "cumulative_session_volume",
        )
    )
    funnel = dict(independent)
    eligible_rows: dict[str, datetime] = {}
    session_dates: set[str] = set()
    evaluation_points = 0
    previous_timestamp = ""
    current_session = ""
    cumulative_volume = 0.0
    row_count = 0

    with item.path.open("r", encoding="utf-8-sig", newline="") as source:
        header_line = source.readline()
        if not header_line:
            raise ValueError("historical source file is empty")
        header = tuple(
            value.strip().strip("<>").upper()
            for value in header_line.rstrip("\r\n").split(",")
        )
        if header != _SOURCE_HEADER:
            raise ValueError("historical source schema is invalid")
        for source_line, line in enumerate(source, start=2):
            if not line.strip():
                continue
            values = tuple(value.strip() for value in line.rstrip("\r\n").split(","))
            if len(values) != len(_SOURCE_HEADER):
                raise ValueError(
                    f"line {source_line}: expected {len(_SOURCE_HEADER)} columns"
                )
            row_count += 1
            ticker, period, date_text, time_text = values[:4]
            normalized_ticker = ticker.upper().removesuffix(".US")
            if normalized_ticker != item.symbol:
                raise ValueError(
                    f"line {source_line}: source symbol {ticker} does not "
                    f"match {item.symbol}"
                )
            if period != "5":
                raise ValueError(f"line {source_line}: period is not five minutes")
            timestamp_key = date_text + time_text.zfill(6)
            if previous_timestamp and timestamp_key <= previous_timestamp:
                raise ValueError(
                    f"line {source_line}: source timestamps are not strictly ordered"
                )
            previous_timestamp = timestamp_key
            if not "20260101" <= date_text <= "20260430":
                continue

            local = _normalized_source_time(date_text, time_text)
            if not EVALUATION_START <= local.date() <= EVALUATION_END:
                continue
            session = local.date().isoformat()
            if session != current_session:
                current_session = session
                cumulative_volume = 0.0
            volume = _number(values[8], "VOL", source_line)
            close = _number(values[7], "CLOSE", source_line)
            if volume < 0 or close <= 0:
                raise ValueError(
                    f"line {source_line}: close must be positive and volume non-negative"
                )
            cumulative_volume += volume
            session_dates.add(session)
            completed_at = local + timedelta(minutes=5)
            session_open = datetime.combine(local.date(), time(9, 30), local.tzinfo)
            session_close = datetime.combine(local.date(), time(16, 0), local.tzinfo)
            elapsed_minutes = int(
                (completed_at - session_open).total_seconds() // 60
            )
            is_boundary = (
                local >= session_open
                and completed_at <= session_close
                and elapsed_minutes > 0
                and elapsed_minutes % 10 == 0
            )
            if not is_boundary:
                continue
            evaluation_points += 1
            independent["valid_regular_session_observation"] += 1
            funnel["valid_regular_session_observation"] += 1
            price_pass = price_is_eligible(close)
            volume_pass = volume_is_eligible(cumulative_volume)
            independent["price_range"] += price_pass
            independent["cumulative_session_volume"] += volume_pass
            if not price_pass:
                continue
            funnel["price_range"] += 1
            if not volume_pass:
                continue
            funnel["cumulative_session_volume"] += 1
            eligible_rows[f"line:{source_line}"] = completed_at

    if row_count == 0:
        raise ValueError("historical source contains no observations")
    return BoundaryScan(
        sessions=len(session_dates),
        evaluation_points=evaluation_points,
        eligible_rows=eligible_rows,
        independent_counts=independent,
        funnel_counts=funnel,
    )


def price_is_eligible(price: float) -> bool:
    return 2.50 <= price <= 8.00


def volume_is_eligible(cumulative_volume: float) -> bool:
    return cumulative_volume > 1_000_000


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


def near_miss_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -int(record["strategy_conditions_passed_count"]),
        str(record["symbol"]),
        str(record["session_date"]),
        str(record["evaluation_timestamp"]),
    )


def retain_near_miss(
    near_misses: list[dict[str, Any]],
    record: dict[str, Any],
    limit: int = 20,
) -> None:
    near_misses.append(record)
    near_misses.sort(key=near_miss_sort_key)
    del near_misses[limit:]


def _git_head(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def compute_run_id(
    *,
    source_manifest_hash: str,
    code_commit: str,
    factor_config: dict[str, Any],
    maximum_files: int | None,
) -> str:
    identity = json.dumps(
        {
            "source_manifest_hash": source_manifest_hash,
            "code_commit": code_commit,
            "evaluation_start": EVALUATION_START.isoformat(),
            "evaluation_end": EVALUATION_END.isoformat(),
            "included_directories": INCLUDED_DIRECTORIES,
            "excluded_directories": EXCLUDED_DIRECTORIES,
            "condition_order": CONDITION_ORDER,
            "factor_config": factor_config,
            "maximum_files": maximum_files,
        },
        sort_keys=True,
    )
    return f"LAUNCH009-{sha256(identity.encode()).hexdigest()[:16].upper()}"


def _selected_bars(bars: tuple[HistoricalBar, ...]) -> tuple[HistoricalBar, ...]:
    sessions_before = sorted(
        {bar.session_date for bar in bars if bar.session_date < EVALUATION_START}
    )[-10:]
    selected_sessions = set(sessions_before)
    return tuple(
        bar
        for bar in bars
        if bar.session_date in selected_sessions
        or EVALUATION_START <= bar.session_date <= EVALUATION_END
    )


def _factor_condition_results(
    factors: OpeningRangeFactors,
) -> dict[str, bool]:
    return {
        "relative_volume": factors.relative_volume >= 4.0,
        "price_change": factors.price_change_pct >= 8.0,
        "rsi": factors.rsi < 40.0,
        "macd_cross": factors.macd_cross_up_below_zero,
    }


def _near_miss_record(
    *,
    factors: OpeningRangeFactors,
    observation: RawMarketData,
    completed_at: datetime,
    condition_results: dict[str, bool],
) -> dict[str, Any]:
    passed = [name for name in STRATEGY_CONDITIONS if condition_results[name]]
    failed = [name for name in STRATEGY_CONDITIONS if not condition_results[name]]
    return {
        "symbol": factors.symbol,
        "session_date": observation.metadata["source_session"],
        "evaluation_timestamp": completed_at.astimezone(timezone.utc).isoformat(),
        "source_bar_timestamp": factors.as_of.isoformat(),
        "current_price": factors.current_price,
        "cumulative_volume": observation.volume,
        "relative_volume": factors.relative_volume,
        "price_change_pct": factors.price_change_pct,
        "rsi": factors.rsi,
        "macd": factors.macd,
        "macd_signal": factors.macd_signal,
        "macd_cross": factors.macd_cross_up_below_zero,
        "strategy_conditions_passed_count": len(passed),
        "conditions_passed": passed,
        "conditions_failed": failed,
        "provenance": {
            "factor_id": factors.object_id,
            "factor_source_market_data_ids": list(
                factors.source_market_data_ids
            ),
            "factor_source_event_sequences": list(
                factors.source_event_sequences
            ),
            "factor_prior_sessions": list(factors.prior_sessions_used),
            "factor_config": factors.calculation_config.to_dict(),
            "source_file": observation.metadata["source_file"],
            "source_file_sha256": observation.metadata["source_file_sha256"],
            "source_row_identifier": observation.metadata[
                "source_row_identifier"
            ],
            "source_timezone": observation.metadata["source_timezone"],
            "source_symbol": observation.metadata["source_symbol"],
            "volume_semantics": observation.metadata["volume_semantics"],
            "code_commit": observation.metadata["code_commit"],
        },
    }


def _empty_counts(keys: Iterable[str]) -> dict[str, int]:
    return {key: 0 for key in keys}


def _process_symbol(
    *,
    item: UniverseFile,
    content_hash: str,
    code_commit: str,
    factor_config: OpeningRangeCalculationConfig,
    decision_journal: DecisionJournal,
    outcome_journal: OutcomeJournal,
    independent: dict[str, int],
    funnel: dict[str, int],
    near_misses: list[dict[str, Any]],
    claimed_sessions: set[tuple[str, str]],
) -> dict[str, Any]:
    boundary_scan = scan_evaluation_boundaries(item)
    eligible_rows = boundary_scan.eligible_rows
    if not eligible_rows:
        for name, count in boundary_scan.independent_counts.items():
            independent[name] += count
        for name, count in boundary_scan.funnel_counts.items():
            funnel[name] += count
        return {
            "sessions": boundary_scan.sessions,
            "evaluation_points": boundary_scan.evaluation_points,
            "signals": 0,
            "signal_sessions": set(),
            "decisions": 0,
            "outcomes": [],
            "factor_attempts": 0,
            "sufficient_factor_points": 0,
            "insufficient_history_points": 0,
            "invalid_market_history_points": 0,
            "factor_history_status": None,
        }

    bars = load_stooq_style_bars(item.path)
    selected_bars = _selected_bars(bars)
    if not selected_bars:
        raise ValueError("eligible source has no selected replay bars")
    for name, count in boundary_scan.independent_counts.items():
        independent[name] += count
    for name, count in boundary_scan.funnel_counts.items():
        funnel[name] += count
    adapter = HistoricalBarReplayAdapter(
        selected_bars,
        source_file=item.path,
        source_file_sha256=content_hash,
        code_commit=code_commit,
        volume_semantics=PER_BAR_VOLUME,
    )
    observations = tuple(adapter.observations())

    market_data_bus = MarketDataBus()
    history = CanonicalMarketHistory(max_observations_per_symbol=1_000)
    snapshot_builder = MarketSnapshotBuilder()
    observer = OutcomeObserver(outcome_journal)
    market_data_bus.subscribe(history)
    market_data_bus.subscribe(snapshot_builder)
    market_data_bus.subscribe(observer)
    calculator = OpeningRangeFactorCalculator(history, factor_config)
    decision_service = PaperDecisionService(decision_journal)
    signals = 0
    signal_sessions: set[str] = set()
    decisions = 0
    factor_attempts = 0
    sufficient_factor_points = 0
    insufficient_history_points = 0
    invalid_market_history_points = 0

    for observation in observations:
        canonical = market_data_bus.ingest(observation)
        row_identifier = str(canonical.metadata["source_row_identifier"])
        completed_at = eligible_rows.get(row_identifier)
        if completed_at is None:
            continue
        factor_attempts += 1
        current_sequence = history.window(canonical.symbol)[-1].sequence_number
        try:
            factors = calculator.calculate(
                canonical.symbol,
                as_of_sequence=current_sequence,
                input_origin=INPUT_ORIGIN,
            )
        except InsufficientHistoryError:
            insufficient_history_points += 1
            continue
        except InvalidMarketHistoryError:
            invalid_market_history_points += 1
            continue
        if max(factors.source_event_sequences) > current_sequence:
            raise ValueError("factor provenance contains a future event")
        independent["sufficient_factor_history"] += 1
        funnel["sufficient_factor_history"] += 1
        sufficient_factor_points += 1
        condition_results = _factor_condition_results(factors)
        for name in STRATEGY_CONDITIONS:
            independent[name] += condition_results[name]

        sequential_pass = True
        for name in STRATEGY_CONDITIONS:
            sequential_pass = sequential_pass and condition_results[name]
            if sequential_pass:
                funnel[name] += 1
        if not all(condition_results.values()):
            retain_near_miss(
                near_misses,
                _near_miss_record(
                    factors=factors,
                    observation=observation,
                    completed_at=completed_at,
                    condition_results=condition_results,
                ),
            )
            continue

        snapshot = snapshot_builder.build()
        generated = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_factors={canonical.symbol: factors},
        ).evaluate(snapshot)
        if len(generated) != 1:
            raise ValueError("unchanged strategy did not confirm factor signal")
        funnel["complete_actionable_signal"] += 1
        signals += 1
        session = str(canonical.metadata["source_session"])
        signal_sessions.add(session)
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
            learning_eligibility=LEARNING_ELIGIBILITY,
        )
        if decision is not None:
            decisions += 1
            observer.observe_decision(decision)

    return {
        "sessions": boundary_scan.sessions,
        "evaluation_points": boundary_scan.evaluation_points,
        "signals": signals,
        "signal_sessions": signal_sessions,
        "decisions": decisions,
        "outcomes": list(observer.outcomes),
        "factor_attempts": factor_attempts,
        "sufficient_factor_points": sufficient_factor_points,
        "insufficient_history_points": insufficient_history_points,
        "invalid_market_history_points": invalid_market_history_points,
        "factor_history_status": (
            "INSUFFICIENT_HISTORY"
            if factor_attempts
            and sufficient_factor_points == 0
            and insufficient_history_points > 0
            else None
        ),
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as destination:
        for value in values:
            destination.write(json.dumps(value, sort_keys=True) + "\n")


def _render_output(
    universe: dict[str, Any],
    processing: dict[str, Any],
    independent: dict[str, int],
    funnel: dict[str, int],
    signals: dict[str, Any],
    evidence: dict[str, Any],
) -> str:
    accuracy = (
        "N/A"
        if evidence["directional_accuracy"] is None
        else f"{evidence['directional_accuracy']:.2%}"
    )
    percent = lambda value: "N/A" if value is None else f"{value:+.6%}"
    money = lambda value: (
        f"+${value:.4f}" if value >= 0 else f"-${abs(value):.4f}"
    )
    lines = [
        "UNIVERSE",
        "Directories included: " + ", ".join(universe["included_directories"]),
        "Directories excluded: " + ", ".join(universe["excluded_directories"]),
        f"Symbols discovered: {universe['symbols_discovered']}",
        f"Symbols processed: {universe['symbols_processed']}",
        f"Files skipped: {universe['files_skipped']}",
        f"Evaluation period: {EVALUATION_START} to {EVALUATION_END}",
        f"Python runtime: {universe['python_executable']} ({universe['python_version']})",
        "",
        "PROCESSING",
        f"Sessions processed: {processing['sessions_processed']}",
        f"Ten-minute evaluation points: {processing['evaluation_points']}",
        "Sufficient-history points: "
        f"{independent['sufficient_factor_history']}",
        f"Runtime duration: {processing['runtime_seconds']:.3f} seconds",
        "",
        "INDEPENDENT CONDITION COUNTS",
        f"Price range: {independent['price_range']}",
        f"Volume: {independent['cumulative_session_volume']}",
        f"Relative volume: {independent['relative_volume']}",
        f"Price change: {independent['price_change']}",
        f"RSI: {independent['rsi']}",
        f"MACD cross: {independent['macd_cross']}",
        "",
        "SEQUENTIAL ATTRITION FUNNEL",
    ]
    for name in CONDITION_ORDER:
        lines.append(f"{name}: {funnel[name]}")
    lines.extend(
        (
            "",
            "SIGNALS",
            f"Signals generated: {signals['signals_generated']}",
            f"Symbols with signals: {signals['symbols_with_signals']}",
            f"Sessions with signals: {signals['sessions_with_signals']}",
            f"Paper decisions: {signals['paper_decisions']}",
            f"Outcomes: {signals['outcomes']}",
            "",
            "EVIDENCE",
            f"Profitable: {evidence['profitable']}",
            f"Unprofitable: {evidence['unprofitable']}",
            f"Flat: {evidence['flat']}",
            f"Directional accuracy: {accuracy}",
            "Cumulative signed return: "
            f"{money(evidence['cumulative_signed_return'])}",
            f"Average return %: {percent(evidence['average_return_pct'])}",
            f"Best: {percent(evidence['best_return_pct'])}",
            f"Worst: {percent(evidence['worst_return_pct'])}",
        )
    )
    if signals["signals_generated"] == 0:
        lines.extend(
            (
                "",
                "UNCHANGED STRATEGY GENERATED ZERO SIGNALS IN THE APPROVED "
                "UNIVERSE AND PERIOD.",
            )
        )
    return "\n".join(lines)


def run_scan(
    source_root: Path,
    output_root: Path,
    *,
    repository: Path | None = None,
    code_commit: str | None = None,
    maximum_files: int | None = None,
) -> tuple[dict[str, Any], str]:
    """Run the bounded, fixed-period LAUNCH-009 evaluator."""

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
    source_hashes, aggregate_hash, hash_errors = build_source_manifest(
        selected_files
    )
    factor_config = OpeningRangeCalculationConfig()
    run_id = compute_run_id(
        source_manifest_hash=aggregate_hash,
        code_commit=commit,
        factor_config=factor_config.to_dict(),
        maximum_files=maximum_files,
    )
    run_directory = output_root.resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    decision_path = run_directory / "decisions.jsonl"
    outcome_path = run_directory / "outcomes.jsonl"
    decision_journal = DecisionJournal(decision_path)
    outcome_journal = OutcomeJournal(outcome_path)
    independent = _empty_counts(CONDITION_ORDER[:-1])
    funnel = _empty_counts(CONDITION_ORDER)
    near_misses: list[dict[str, Any]] = []
    claimed_sessions: set[tuple[str, str]] = set()
    errors = list(hash_errors)
    symbols_processed = 0
    sessions_processed = 0
    evaluation_points = 0
    signals_generated = 0
    signal_symbols: set[str] = set()
    signal_symbol_sessions: set[tuple[str, str]] = set()
    paper_decisions = 0
    insufficient_history_points = 0
    invalid_market_history_points = 0
    factor_history_statuses: list[dict[str, Any]] = []

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
                    decision_journal=decision_journal,
                    outcome_journal=outcome_journal,
                    independent=independent,
                    funnel=funnel,
                    near_misses=near_misses,
                    claimed_sessions=claimed_sessions,
                )
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append(
                    {"file": item.relative_path, "error": str(exc)}
                )
                continue
            symbols_processed += 1
            sessions_processed += int(result["sessions"])
            evaluation_points += int(result["evaluation_points"])
            symbol_signals = int(result["signals"])
            signals_generated += symbol_signals
            if symbol_signals:
                signal_symbols.add(item.symbol)
                signal_symbol_sessions.update(
                    (item.symbol, session)
                    for session in result["signal_sessions"]
                )
            paper_decisions += int(result["decisions"])
            insufficient_history_points += int(
                result["insufficient_history_points"]
            )
            invalid_market_history_points += int(
                result["invalid_market_history_points"]
            )
            if result["factor_history_status"] is not None:
                factor_history_statuses.append(
                    {
                        "symbol": item.symbol,
                        "status": result["factor_history_status"],
                        "factor_attempts": int(result["factor_attempts"]),
                    }
                )
    finally:
        system_clock.set_mode(ClockMode.LIVE)

    runtime_ended = system_clock.now()
    runtime_seconds = system_clock.monotonic() - monotonic_started
    outcome_records = OutcomeJournal(outcome_path).records()
    returns = [float(record["signed_return_pct"]) for record in outcome_records]
    directional = [
        record["directional_correct"]
        for record in outcome_records
        if record["directional_correct"] is not None
    ]
    evidence = {
        "profitable": sum(record["signed_return"] > 0 for record in outcome_records),
        "unprofitable": sum(
            record["signed_return"] < 0 for record in outcome_records
        ),
        "flat": sum(record["signed_return"] == 0 for record in outcome_records),
        "directional_accuracy": (
            sum(value is True for value in directional) / len(directional)
            if directional
            else None
        ),
        "cumulative_signed_return": sum(
            float(record["signed_return"]) for record in outcome_records
        ),
        "average_return_pct": statistics.fmean(returns) if returns else None,
        "median_return_pct": statistics.median(returns) if returns else None,
        "best_return_pct": max(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "classification": LEARNING_ELIGIBILITY,
        "complete_position_lifecycle": False,
        "live_or_forward": False,
    }
    universe_summary = {
        "source_root": str(source_root.resolve()),
        "included_directories": list(inventory.included_directories),
        "excluded_directories": list(inventory.excluded_directories),
        "classification_ambiguity": (
            "Stock-labeled directories may contain exchange-listed units, "
            "warrants, or preferreds; no filename inference was applied."
        ),
        "archive_file_count": inventory.archive_file_count,
        "excluded_file_count": inventory.excluded_file_count,
        "included_files_discovered": len(inventory.files),
        "selected_file_count": len(selected_files),
        "symbols_discovered": len(inventory.files),
        "symbols_processed": symbols_processed,
        "duplicate_symbol_count": inventory.duplicate_symbol_count,
        "duplicate_handling": (
            "lexicographically first source path retained per symbol"
        ),
        "duplicate_files_skipped": list(inventory.duplicate_files_skipped),
        "malformed_or_skipped_file_count": len(errors),
        "files_skipped": len(errors) + len(inventory.duplicate_files_skipped),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "production_evidence_mode": maximum_files is None,
    }
    processing = {
        "sessions_processed": sessions_processed,
        "evaluation_points": evaluation_points,
        "runtime_started": runtime_started.isoformat(),
        "runtime_ended": runtime_ended.isoformat(),
        "runtime_seconds": runtime_seconds,
        "factor_history": {
            "insufficient_history_points": insufficient_history_points,
            "invalid_market_history_points": invalid_market_history_points,
            "symbol_statuses": factor_history_statuses,
        },
    }
    signal_summary = {
        "signals_generated": signals_generated,
        "symbols_with_signals": len(signal_symbols),
        "sessions_with_signals": len(signal_symbol_sessions),
        "paper_decisions": paper_decisions,
        "outcomes": len(outcome_records),
        "signal_symbols": sorted(signal_symbols),
        "signal_symbol_sessions": [
            {"symbol": symbol, "session": session}
            for symbol, session in sorted(signal_symbol_sessions)
        ],
    }
    attrition = {
        "condition_order": list(CONDITION_ORDER),
        "independent_counts": independent,
        "sequential_funnel": funnel,
    }
    summary = {
        "run_id": run_id,
        "universe": universe_summary,
        "processing": processing,
        "attrition": attrition,
        "signals": signal_summary,
        "evidence": evidence,
        "near_miss_count": len(near_misses),
    }
    artifact_paths = {
        "manifest": str(run_directory / "manifest.json"),
        "universe_summary": str(run_directory / "universe_summary.json"),
        "attrition_funnel": str(run_directory / "attrition_funnel.json"),
        "near_misses": str(run_directory / "near_misses.jsonl"),
        "summary": str(run_directory / "summary.json"),
        "decisions": str(decision_path) if decision_path.exists() else None,
        "outcomes": str(outcome_path) if outcome_path.exists() else None,
    }
    manifest = {
        "run_id": run_id,
        "code_commit": commit,
        "production_evidence_mode": maximum_files is None,
        "source_root": str(source_root.resolve()),
        "source_file_count": len(selected_files),
        "source_dataset_aggregate_sha256": aggregate_hash,
        "universe_inclusion_rules": list(INCLUDED_DIRECTORIES),
        "universe_exclusion_rules": list(EXCLUDED_DIRECTORIES),
        "evaluation_period": {
            "start": EVALUATION_START.isoformat(),
            "end": EVALUATION_END.isoformat(),
            "earlier_sessions_used_for_lookback_only": True,
        },
        "python": {
            "executable": universe_summary["python_executable"],
            "version": universe_summary["python_version"],
        },
        "strategy": {
            "name": OpeningRangeStrategy.name,
            "thresholds": {
                "relative_volume_minimum": 4.0,
                "price_change_pct_minimum": 8.0,
                "rsi_maximum_exclusive": 40.0,
                "macd_upward_cross_below_zero": True,
            },
            "factor_config": factor_config.to_dict(),
            "evaluation_cadence": (
                "completed ten-minute boundaries from five-minute bars"
            ),
            "condition_order": list(CONDITION_ORDER),
            "maximum_decisions_per_symbol_session": 1,
        },
        "outcome_horizon": "NEXT_CANONICAL_OBSERVATION",
        "input_origin": INPUT_ORIGIN,
        "learning_eligibility": LEARNING_ELIGIBILITY,
        "runtime": processing,
        "errors_and_skipped_files": errors,
        "artifacts": artifact_paths,
    }
    _write_json(run_directory / "universe_summary.json", universe_summary)
    _write_json(run_directory / "attrition_funnel.json", attrition)
    _write_jsonl(run_directory / "near_misses.jsonl", near_misses)
    _write_json(run_directory / "summary.json", summary)
    _write_json(run_directory / "manifest.json", manifest)
    output = _render_output(
        universe_summary,
        processing,
        independent,
        funnel,
        signal_summary,
        evidence,
    )
    return summary, output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("runs/real_universe_scan"),
    )
    parser.add_argument("--maximum-files", type=int)
    arguments = parser.parse_args()
    _, output = run_scan(
        arguments.source_root,
        arguments.output_root,
        maximum_files=arguments.maximum_files,
    )
    print(output)


if __name__ == "__main__":
    main()
