"""Deterministic Opening Range factors from canonical market history."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from math import isclose, isfinite
from types import MappingProxyType
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from aegis.clock.utc import ensure_utc
from aegis.domain import DomainObject

from .history import CanonicalMarketHistory, MarketHistoryObservation


CANONICAL_FACTOR_ORIGIN = (
    "CANONICAL_REPLAY_WITH_MARKET_DERIVED_STRATEGY_FACTORS"
)
SYNTHETIC_FACTOR_ORIGIN = (
    "SYNTHETIC_CANONICAL_REPLAY_WITH_MARKET_DERIVED_FACTORS"
)
CANONICAL_REPLAY_STRATEGY_EVIDENCE = "CANONICAL_REPLAY_STRATEGY_EVIDENCE"


class InsufficientHistoryError(ValueError):
    """Structured failure when a factor cannot be calculated truthfully."""

    def __init__(self, factor: str, required: int, available: int) -> None:
        self.factor = factor
        self.required = required
        self.available = available
        super().__init__(
            f"insufficient {factor} history: required {required}, "
            f"available {available}"
        )


class InvalidMarketHistoryError(ValueError):
    """Canonical observations violate cumulative-market-data semantics."""


@dataclass(frozen=True)
class OpeningRangeCalculationConfig:
    rsi_period: int = 14
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9
    volume_bucket_minutes: int = 10
    relative_volume_lookback_sessions: int = 10
    session_timezone: str = "America/New_York"
    session_open: time = time(9, 30)

    def __post_init__(self) -> None:
        if self.rsi_period <= 0:
            raise ValueError("RSI period must be greater than zero")
        if self.macd_fast_period <= 0:
            raise ValueError("MACD fast period must be greater than zero")
        if self.macd_slow_period <= self.macd_fast_period:
            raise ValueError("MACD slow period must exceed fast period")
        if self.macd_signal_period <= 0:
            raise ValueError("MACD signal period must be greater than zero")
        if self.volume_bucket_minutes <= 0:
            raise ValueError("volume bucket minutes must be greater than zero")
        if self.relative_volume_lookback_sessions <= 0:
            raise ValueError("relative-volume lookback must be greater than zero")
        ZoneInfo(self.session_timezone)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rsi_period": self.rsi_period,
            "macd_fast_period": self.macd_fast_period,
            "macd_slow_period": self.macd_slow_period,
            "macd_signal_period": self.macd_signal_period,
            "volume_bucket_minutes": self.volume_bucket_minutes,
            "relative_volume_lookback_sessions": (
                self.relative_volume_lookback_sessions
            ),
            "session_timezone": self.session_timezone,
            "session_open": self.session_open.isoformat(timespec="minutes"),
        }


@dataclass(frozen=True)
class MACDCalculation:
    macd: float
    signal: float
    previous_macd: float
    previous_signal: float
    cross_up_below_zero: bool


def calculate_wilder_rsi(prices: Iterable[float], period: int = 14) -> float:
    values = tuple(float(value) for value in prices)
    required = period + 1
    if len(values) < required:
        raise InsufficientHistoryError("RSI", required, len(values))

    changes = tuple(current - previous for previous, current in zip(values, values[1:]))
    gains = tuple(max(change, 0.0) for change in changes)
    losses = tuple(max(-change, 0.0) for change in changes)
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period

    if isclose(average_loss, 0.0):
        return 50.0 if isclose(average_gain, 0.0) else 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def _ema(values: tuple[float, ...], period: int) -> tuple[float | None, ...]:
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(values[:period]) / period
    result: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for value in values[period:]:
        previous = (alpha * value) + ((1.0 - alpha) * previous)
        result.append(previous)
    return tuple(result)


def calculate_macd(
    prices: Iterable[float],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDCalculation:
    values = tuple(float(value) for value in prices)
    required = slow_period + signal_period
    if len(values) < required:
        raise InsufficientHistoryError("MACD", required, len(values))

    fast = _ema(values, fast_period)
    slow = _ema(values, slow_period)
    macd_values = tuple(
        float(fast[index]) - float(slow[index])
        for index in range(slow_period - 1, len(values))
    )
    signals = _ema(macd_values, signal_period)
    current_macd = macd_values[-1]
    previous_macd = macd_values[-2]
    current_signal = signals[-1]
    previous_signal = signals[-2]
    if current_signal is None or previous_signal is None:
        raise InsufficientHistoryError("MACD", required, len(values))
    return MACDCalculation(
        macd=current_macd,
        signal=current_signal,
        previous_macd=previous_macd,
        previous_signal=previous_signal,
        cross_up_below_zero=(
            previous_macd <= previous_signal
            and current_macd > current_signal
            and current_macd < 0.0
        ),
    )


@dataclass(frozen=True, kw_only=True)
class OpeningRangeFactors(DomainObject):
    symbol: str
    as_of: datetime
    session_open_price: float
    current_price: float
    relative_volume: float
    price_change_pct: float
    rsi: float
    macd: float
    macd_signal: float
    macd_cross_up_below_zero: bool
    source_market_data_ids: tuple[str, ...]
    source_event_sequences: tuple[int, ...]
    calculation_config: OpeningRangeCalculationConfig
    input_origin: str
    prior_sessions_used: tuple[str, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "as_of", ensure_utc(self.as_of))
        object.__setattr__(
            self,
            "source_market_data_ids",
            tuple(self.source_market_data_ids),
        )
        object.__setattr__(
            self,
            "source_event_sequences",
            tuple(self.source_event_sequences),
        )
        object.__setattr__(
            self,
            "prior_sessions_used",
            tuple(self.prior_sessions_used),
        )

    def strategy_values(self) -> MappingProxyType:
        return MappingProxyType(
            {
                "relative_volume": self.relative_volume,
                "price_change_pct": self.price_change_pct,
                "rsi": self.rsi,
                "macd": self.macd,
                "macd_signal": self.macd_signal,
                "macd_cross": self.macd_cross_up_below_zero,
            }
        )


class OpeningRangeFactorCalculator:
    """Calculate one pinned ORB factor object from canonical observations."""

    def __init__(
        self,
        history: CanonicalMarketHistory,
        config: OpeningRangeCalculationConfig | None = None,
    ) -> None:
        self._history = history
        self._config = config or OpeningRangeCalculationConfig()

    def calculate(
        self,
        symbol: str,
        *,
        as_of_sequence: int | None = None,
        input_origin: str = CANONICAL_FACTOR_ORIGIN,
    ) -> OpeningRangeFactors:
        normalized_symbol = symbol.strip().upper()
        observations = self._history.window(
            normalized_symbol,
            through_sequence=as_of_sequence,
        )
        if not observations:
            raise InsufficientHistoryError("market", 1, 0)

        timezone = ZoneInfo(self._config.session_timezone)
        grouped = self._group_sessions(observations, timezone)
        self._validate_cumulative_volume(grouped)
        current = observations[-1]
        current_session = current.market_data.source_timestamp.astimezone(
            timezone
        ).date()
        current_entries = tuple(
            item
            for item in grouped.get(current_session, ())
            if item.market_data.source_timestamp.astimezone(timezone).time()
            >= self._config.session_open
        )
        if not current_entries:
            raise InsufficientHistoryError("current session", 1, 0)

        prices = tuple(item.market_data.last for item in current_entries)
        rsi = calculate_wilder_rsi(prices, self._config.rsi_period)
        macd = calculate_macd(
            prices,
            fast_period=self._config.macd_fast_period,
            slow_period=self._config.macd_slow_period,
            signal_period=self._config.macd_signal_period,
        )
        first_regular_observation = current_entries[0].market_data
        source_open = first_regular_observation.metadata.get("source_open")
        try:
            session_open_price = (
                first_regular_observation.last
                if source_open is None
                else float(source_open)
            )
        except (TypeError, ValueError) as exc:
            raise InvalidMarketHistoryError(
                "source_open must be numeric when present"
            ) from exc
        if not isfinite(session_open_price) or session_open_price <= 0:
            raise InvalidMarketHistoryError(
                "session open price must be finite and positive"
            )
        price_change_pct = (
            (current.market_data.last - session_open_price)
            / session_open_price
        ) * 100.0

        relative_volume, prior_sessions, volume_sources = (
            self._relative_volume(
                grouped,
                current_session,
                current,
                timezone,
            )
        )
        source_by_sequence = {
            item.sequence_number: item
            for item in (*current_entries, *volume_sources)
        }
        sources = tuple(source_by_sequence[key] for key in sorted(source_by_sequence))
        config_record = self._config.to_dict()
        identity_key = repr(
            (
                normalized_symbol,
                current.sequence_number,
                tuple(item.market_data.object_id for item in sources),
                config_record,
                input_origin,
            )
        )
        return OpeningRangeFactors(
            object_id=(
                f"ORB-{sha256(identity_key.encode()).hexdigest()[:16].upper()}"
            ),
            created_at=current.market_data.received_at,
            trace_id=current.market_data.trace_id,
            correlation_id=current.market_data.correlation_id,
            symbol=normalized_symbol,
            as_of=current.market_data.source_timestamp,
            session_open_price=session_open_price,
            current_price=current.market_data.last,
            relative_volume=relative_volume,
            price_change_pct=price_change_pct,
            rsi=rsi,
            macd=macd.macd,
            macd_signal=macd.signal,
            macd_cross_up_below_zero=macd.cross_up_below_zero,
            source_market_data_ids=tuple(
                item.market_data.object_id for item in sources
            ),
            source_event_sequences=tuple(
                item.sequence_number for item in sources
            ),
            calculation_config=self._config,
            input_origin=input_origin,
            prior_sessions_used=tuple(day.isoformat() for day in prior_sessions),
        )

    @staticmethod
    def _group_sessions(
        observations: tuple[MarketHistoryObservation, ...],
        timezone: ZoneInfo,
    ) -> dict[date, tuple[MarketHistoryObservation, ...]]:
        grouped: dict[date, list[MarketHistoryObservation]] = {}
        for item in observations:
            session = item.market_data.source_timestamp.astimezone(timezone).date()
            grouped.setdefault(session, []).append(item)
        return {key: tuple(value) for key, value in grouped.items()}

    @staticmethod
    def _validate_cumulative_volume(
        grouped: dict[date, tuple[MarketHistoryObservation, ...]],
    ) -> None:
        for session, entries in grouped.items():
            previous = None
            for item in entries:
                volume = item.market_data.volume
                if previous is not None and volume < previous:
                    raise InvalidMarketHistoryError(
                        f"cumulative volume decreased in session {session}"
                    )
                previous = volume

    def _relative_volume(
        self,
        grouped: dict[date, tuple[MarketHistoryObservation, ...]],
        current_session: date,
        current: MarketHistoryObservation,
        timezone: ZoneInfo,
    ) -> tuple[
        float,
        tuple[date, ...],
        tuple[MarketHistoryObservation, ...],
    ]:
        current_local = current.market_data.source_timestamp.astimezone(timezone)
        session_open = datetime.combine(
            current_session,
            self._config.session_open,
            tzinfo=timezone,
        )
        if current_local < session_open:
            raise InvalidMarketHistoryError(
                "current observation occurs before regular-session open"
            )
        elapsed_minutes = int((current_local - session_open).total_seconds() // 60)
        bucket_index = elapsed_minutes // self._config.volume_bucket_minutes
        bucket_offset = timedelta(
            minutes=bucket_index * self._config.volume_bucket_minutes
        )
        current_start = session_open + bucket_offset
        current_entries = grouped[current_session]
        current_boundary = self._latest_at_or_before(
            current_entries,
            current_start,
            timezone,
        )
        if current_boundary is None:
            raise InsufficientHistoryError("current volume bucket", 1, 0)
        current_bucket_volume = (
            current.market_data.volume - current_boundary.market_data.volume
        )
        if current_bucket_volume < 0:
            raise InvalidMarketHistoryError(
                "current cumulative volume is below its bucket boundary"
            )

        historical_volumes: list[float] = []
        sessions: list[date] = []
        sources: list[MarketHistoryObservation] = [current_boundary, current]
        for session in sorted(
            (day for day in grouped if day < current_session),
            reverse=True,
        ):
            session_open_at = datetime.combine(
                session,
                self._config.session_open,
                tzinfo=timezone,
            )
            start = session_open_at + bucket_offset
            end = start + timedelta(
                minutes=self._config.volume_bucket_minutes
            )
            entries = grouped[session]
            if entries[-1].market_data.source_timestamp.astimezone(timezone) < end:
                continue
            start_entry = self._latest_at_or_before(entries, start, timezone)
            end_entry = self._latest_at_or_before(entries, end, timezone)
            if start_entry is None or end_entry is None:
                continue
            bucket_volume = (
                end_entry.market_data.volume - start_entry.market_data.volume
            )
            if bucket_volume < 0:
                raise InvalidMarketHistoryError(
                    f"negative volume bucket in session {session}"
                )
            historical_volumes.append(bucket_volume)
            sessions.append(session)
            sources.extend((start_entry, end_entry))
            if len(sessions) == self._config.relative_volume_lookback_sessions:
                break

        required = self._config.relative_volume_lookback_sessions
        if len(sessions) < required:
            raise InsufficientHistoryError(
                "relative volume sessions",
                required,
                len(sessions),
            )
        historical_average = sum(historical_volumes) / len(historical_volumes)
        if historical_average == 0:
            raise InvalidMarketHistoryError(
                "historical average bucket volume cannot be zero"
            )
        return (
            current_bucket_volume / historical_average,
            tuple(sessions),
            tuple(sources),
        )

    @staticmethod
    def _latest_at_or_before(
        entries: tuple[MarketHistoryObservation, ...],
        boundary: datetime,
        timezone: ZoneInfo,
    ) -> MarketHistoryObservation | None:
        eligible = tuple(
            item
            for item in entries
            if item.market_data.source_timestamp.astimezone(timezone) <= boundary
        )
        return eligible[-1] if eligible else None
