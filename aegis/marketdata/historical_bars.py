"""Minimal local Stooq-style OHLCV replay adapter."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from .models import RawMarketData


REAL_HISTORICAL_FACTOR_ORIGIN = (
    "REAL_HISTORICAL_LOCAL_OHLCV_REPLAY_WITH_MARKET_DERIVED_FACTORS"
)
REAL_HISTORICAL_LEARNING_ELIGIBILITY = (
    "REAL_HISTORICAL_REPLAY_NEXT_OBSERVATION_EVIDENCE"
)
OHLCV_OBSERVATION_TYPE = "OHLCV_BAR"
PER_BAR_VOLUME = "PER_BAR"
UNKNOWN_VOLUME = "UNKNOWN"
STOOQ_STYLE_PROVIDER = "Stooq-style local archive"
STOOQ_STYLE_PROVIDER_CONFIDENCE = "MEDIUM"
SOURCE_TIMEZONE = "Europe/Warsaw"
SESSION_TIMEZONE = "America/New_York"

_REQUIRED_COLUMNS = (
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


@dataclass(frozen=True)
class HistoricalBar:
    """One validated source row with normalized timestamps."""

    source_line: int
    source_symbol: str
    period_minutes: int
    raw_timestamp: datetime
    utc_timestamp: datetime
    new_york_timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float

    @property
    def symbol(self) -> str:
        return self.source_symbol.removesuffix(".US").upper()

    @property
    def session_date(self) -> date:
        return self.new_york_timestamp.date()


@dataclass(frozen=True)
class VolumeSemantics:
    classification: str
    within_session_comparisons: int
    within_session_decreases: int


@dataclass(frozen=True)
class TimezoneValidationSample:
    session: date
    raw_open: datetime
    raw_close: datetime
    utc_open: datetime
    utc_close: datetime
    new_york_open: datetime
    new_york_close: datetime
    passed: bool


def file_sha256(path: Path | str) -> str:
    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _number(value: str, field_name: str, source_line: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"line {source_line}: {field_name} must be numeric"
        ) from exc
    if not isfinite(number):
        raise ValueError(f"line {source_line}: {field_name} must be finite")
    return number


def load_stooq_style_bars(
    path: Path | str,
    *,
    source_timezone: str = SOURCE_TIMEZONE,
    session_timezone: str = SESSION_TIMEZONE,
) -> tuple[HistoricalBar, ...]:
    """Load and validate one local per-symbol Stooq-style text file."""

    source_path = Path(path)
    source_zone = ZoneInfo(source_timezone)
    session_zone = ZoneInfo(session_timezone)
    bars: list[HistoricalBar] = []
    with source_path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = csv.reader(source)
        try:
            header = tuple(column.strip().strip("<>").upper() for column in next(rows))
        except StopIteration as exc:
            raise ValueError("historical source file is empty") from exc
        if header != _REQUIRED_COLUMNS:
            raise ValueError(
                "historical source schema does not match the required "
                "Stooq-style OHLCV columns"
            )

        for source_line, values in enumerate(rows, start=2):
            if not values or not any(value.strip() for value in values):
                continue
            if len(values) != len(header):
                raise ValueError(
                    f"line {source_line}: expected {len(header)} columns"
                )
            row = dict(zip(header, (value.strip() for value in values)))
            try:
                naive_timestamp = datetime.strptime(
                    row["DATE"] + row["TIME"].zfill(6),
                    "%Y%m%d%H%M%S",
                )
                period_minutes = int(row["PER"])
            except ValueError as exc:
                raise ValueError(
                    f"line {source_line}: invalid date, time, or period"
                ) from exc
            if period_minutes <= 0:
                raise ValueError(f"line {source_line}: period must be positive")

            source_timestamp = naive_timestamp.replace(tzinfo=source_zone)
            utc_timestamp = source_timestamp.astimezone(timezone.utc)
            new_york_timestamp = utc_timestamp.astimezone(session_zone)
            open_price = _number(row["OPEN"], "OPEN", source_line)
            high = _number(row["HIGH"], "HIGH", source_line)
            low = _number(row["LOW"], "LOW", source_line)
            close = _number(row["CLOSE"], "CLOSE", source_line)
            volume = _number(row["VOL"], "VOL", source_line)
            open_interest = _number(row["OPENINT"], "OPENINT", source_line)
            if min(open_price, high, low, close) <= 0:
                raise ValueError(f"line {source_line}: OHLC prices must be positive")
            if high < max(open_price, low, close) or low > min(
                open_price,
                high,
                close,
            ):
                raise ValueError(f"line {source_line}: invalid OHLC range")
            if volume < 0:
                raise ValueError(f"line {source_line}: volume cannot be negative")

            bars.append(
                HistoricalBar(
                    source_line=source_line,
                    source_symbol=row["TICKER"].upper(),
                    period_minutes=period_minutes,
                    raw_timestamp=source_timestamp,
                    utc_timestamp=utc_timestamp,
                    new_york_timestamp=new_york_timestamp,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    open_interest=open_interest,
                )
            )

    ordered = tuple(
        sorted(bars, key=lambda bar: (bar.utc_timestamp, bar.source_line))
    )
    if not ordered:
        raise ValueError("historical source contains no observations")
    identities = {
        (bar.source_symbol, bar.utc_timestamp) for bar in ordered
    }
    if len(identities) != len(ordered):
        raise ValueError("historical source contains duplicate symbol timestamps")
    return ordered


def determine_volume_semantics(
    bars: tuple[HistoricalBar, ...],
) -> VolumeSemantics:
    """Classify source volume from within-session behavior."""

    comparisons = 0
    decreases = 0
    previous_by_session: dict[tuple[str, date], float] = {}
    for bar in bars:
        key = (bar.source_symbol, bar.session_date)
        previous = previous_by_session.get(key)
        if previous is not None:
            comparisons += 1
            decreases += bar.volume < previous
        previous_by_session[key] = bar.volume
    classification = PER_BAR_VOLUME if decreases else UNKNOWN_VOLUME
    return VolumeSemantics(classification, comparisons, decreases)


def validate_timezone_sessions(
    bars: tuple[HistoricalBar, ...],
    sample_dates: tuple[date, ...],
) -> tuple[TimezoneValidationSample, ...]:
    """Confirm sampled rows align to a US regular-session bar grid."""

    samples: list[TimezoneValidationSample] = []
    for session in sample_dates:
        entries = tuple(bar for bar in bars if bar.session_date == session)
        if not entries:
            raise ValueError(f"timezone sample session is absent: {session}")
        first, last = entries[0], entries[-1]
        passed = (
            first.new_york_timestamp.time() == time(9, 30)
            and time(15, 55) <= last.new_york_timestamp.time() <= time(16, 0)
        )
        samples.append(
            TimezoneValidationSample(
                session=session,
                raw_open=first.raw_timestamp,
                raw_close=last.raw_timestamp,
                utc_open=first.utc_timestamp,
                utc_close=last.utc_timestamp,
                new_york_open=first.new_york_timestamp,
                new_york_close=last.new_york_timestamp,
                passed=passed,
            )
        )
    return tuple(samples)


class HistoricalBarReplayAdapter:
    """Adapt validated OHLCV rows to the existing ingestion boundary."""

    def __init__(
        self,
        bars: tuple[HistoricalBar, ...],
        *,
        source_file: Path | str,
        source_file_sha256: str,
        code_commit: str,
        volume_semantics: str = PER_BAR_VOLUME,
        provider: str = STOOQ_STYLE_PROVIDER,
        provider_confidence: str = STOOQ_STYLE_PROVIDER_CONFIDENCE,
    ) -> None:
        if volume_semantics != PER_BAR_VOLUME:
            raise ValueError("historical replay requires proven per-bar volume")
        self._bars = bars
        self._source_file = str(Path(source_file).resolve())
        self._source_file_sha256 = source_file_sha256.upper()
        self._code_commit = code_commit
        self._volume_semantics = volume_semantics
        self._provider = provider
        self._provider_confidence = provider_confidence

    def observations(self) -> Iterator[RawMarketData]:
        cumulative_by_session: dict[tuple[str, date], float] = {}
        for bar in self._bars:
            session_key = (bar.source_symbol, bar.session_date)
            cumulative = cumulative_by_session.get(session_key, 0.0) + bar.volume
            cumulative_by_session[session_key] = cumulative
            metadata = {
                "observation_type": OHLCV_OBSERVATION_TYPE,
                "source_open": bar.open,
                "source_high": bar.high,
                "source_low": bar.low,
                "source_close": bar.close,
                "source_bar_volume": bar.volume,
                "derived_cumulative_session_volume": cumulative,
                "source_timezone": SOURCE_TIMEZONE,
                "normalized_utc_timestamp": bar.utc_timestamp.isoformat(),
                "normalized_new_york_timestamp": (
                    bar.new_york_timestamp.isoformat()
                ),
                "source_file": self._source_file,
                "source_file_sha256": self._source_file_sha256,
                "source_row_identifier": f"line:{bar.source_line}",
                "source_provider": self._provider,
                "source_provider_confidence": self._provider_confidence,
                "source_symbol": bar.source_symbol,
                "source_session": bar.session_date.isoformat(),
                "source_period_minutes": bar.period_minutes,
                "source_open_interest": bar.open_interest,
                "volume_semantics": self._volume_semantics,
                "code_commit": self._code_commit,
            }
            yield RawMarketData(
                symbol=bar.symbol,
                exchange="",
                bid=None,
                ask=None,
                last=bar.close,
                volume=cumulative,
                source="real-historical-local-ohlcv",
                source_timestamp=bar.utc_timestamp,
                metadata=metadata,
            )
