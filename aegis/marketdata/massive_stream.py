"""Bounded Massive U.S. equities WebSocket market-data adapter."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
from math import ceil, isfinite
import os
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect

from aegis.clock import system_clock

from .live_models import LiveQuote, LiveTrade


MASSIVE_API_KEY = "MASSIVE_API_KEY"
MASSIVE_DATA_MODE = "MASSIVE_DATA_MODE"
MASSIVE_WS_URL = "MASSIVE_WS_URL"
MASSIVE_DELAYED_WS_URL = "wss://delayed.massive.com/stocks"
MASSIVE_REALTIME_WS_URL = "wss://socket.massive.com/stocks"
DEFAULT_MASSIVE_WS_URL = MASSIVE_DELAYED_WS_URL
DEFAULT_MASSIVE_SYMBOLS = ("SPY", "QQQ", "NVDA", "AAPL", "TSLA")
MAX_MASSIVE_SYMBOLS = 20
MAX_DIAGNOSTIC_SAMPLES_PER_REASON = 5


@dataclass(frozen=True)
class _ConditionUpdateRule:
    updates_high_low: bool
    updates_open_close: bool
    updates_volume: bool


@dataclass(frozen=True)
class _TradeEligibility:
    updates_high_low: bool
    updates_open_close: bool
    updates_volume: bool
    unresolved_conditions: tuple[str, ...]


# Consolidated rules for every condition observed in the saved LAUNCH-011F
# sample. Massive's documented combination rule makes any False take precedence.
_MASSIVE_SAMPLE_CONDITION_RULES = {
    "2": _ConditionUpdateRule(False, False, True),
    "10": _ConditionUpdateRule(True, False, True),
    "14": _ConditionUpdateRule(True, True, True),
    "37": _ConditionUpdateRule(False, False, True),
    "41": _ConditionUpdateRule(True, True, True),
    "52": _ConditionUpdateRule(False, False, True),
    "53": _ConditionUpdateRule(False, False, True),
}


class MassiveMessageClassification(str, Enum):
    ACCEPTED_TRADE = "accepted_trade"
    ACCEPTED_QUOTE = "accepted_quote"
    RECOGNIZED_CONTROL = "recognized_control"
    INTENTIONALLY_IGNORED_DOCUMENTED = "intentionally_ignored_documented"
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    INVALID_JSON_OR_PAYLOAD_STRUCTURE = "invalid_json_or_payload_structure"
    MISSING_OR_INVALID_SYMBOL = "missing_or_invalid_symbol"
    MISSING_OR_INVALID_TIMESTAMP = "missing_or_invalid_timestamp"
    MISSING_OR_INVALID_PRICE = "missing_or_invalid_price"
    MISSING_OR_INVALID_SIZE = "missing_or_invalid_size"
    OTHER_DOMAIN_VALIDATION_FAILURE = "other_domain_validation_failure"


DOCUMENTED_IGNORED_EVENT_TYPES = frozenset({"A", "AM", "FMV", "LULD", "NOI"})
_MALFORMED_CLASSIFICATIONS = frozenset(
    {
        MassiveMessageClassification.UNKNOWN_EVENT_TYPE,
        MassiveMessageClassification.INVALID_JSON_OR_PAYLOAD_STRUCTURE,
        MassiveMessageClassification.MISSING_OR_INVALID_SYMBOL,
        MassiveMessageClassification.MISSING_OR_INVALID_TIMESTAMP,
        MassiveMessageClassification.MISSING_OR_INVALID_PRICE,
        MassiveMessageClassification.MISSING_OR_INVALID_SIZE,
        MassiveMessageClassification.OTHER_DOMAIN_VALIDATION_FAILURE,
    }
)
_SAFE_MARKET_DATA_FIELDS = (
    "ev",
    "sym",
    "p",
    "s",
    "ds",
    "x",
    "i",
    "c",
    "t",
    "pt",
    "q",
    "z",
    "trfi",
    "trft",
    "bp",
    "bs",
    "bx",
    "ap",
    "as",
    "ax",
    "o",
    "h",
    "l",
    "v",
    "av",
    "e",
    "op",
)


@dataclass(frozen=True)
class MassiveMessageDiagnostics:
    messages_received: int
    total_classified: int
    counts_reconcile: bool
    classification_counts: tuple[tuple[str, int], ...]
    malformed_classified: int
    malformed_counts_reconcile: bool
    delivery_failures: int
    captured_samples: int

    def count(self, classification: MassiveMessageClassification | str) -> int:
        key = (
            classification.value
            if isinstance(classification, MassiveMessageClassification)
            else str(classification)
        )
        return dict(self.classification_counts).get(key, 0)


class _MessageValidationError(ValueError):
    def __init__(
        self,
        classification: MassiveMessageClassification,
        *,
        field: str,
        value: object,
        reason_key: str,
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.classification = classification
        self.field = field
        self.value = value
        self.reason_key = reason_key
        self.reason = reason


class MissingMassiveCredentialError(RuntimeError):
    pass


class MassiveDataMode(str, Enum):
    DELAYED_TRADES = "delayed"
    REALTIME_TRADES_QUOTES = "realtime"

    @classmethod
    def parse(cls, value: "MassiveDataMode | str") -> "MassiveDataMode":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError("MASSIVE_DATA_MODE must be delayed or realtime") from exc

    @property
    def endpoint(self) -> str:
        if self == MassiveDataMode.DELAYED_TRADES:
            return MASSIVE_DELAYED_WS_URL
        return MASSIVE_REALTIME_WS_URL

    @property
    def coverage_classification(self) -> str:
        if self == MassiveDataMode.DELAYED_TRADES:
            return "FULL_MARKET_DELAYED_TRADES"
        return "REALTIME_TRADES_AND_NBBO_QUOTES"

    @property
    def evidence_classification(self) -> str:
        if self == MassiveDataMode.DELAYED_TRADES:
            return "DELAYED_MARKET_DATA"
        return "REALTIME_MARKET_DATA"

    @property
    def quote_entitlement(self) -> bool:
        return self == MassiveDataMode.REALTIME_TRADES_QUOTES

    @property
    def execution_reference_eligible(self) -> bool:
        return self == MassiveDataMode.REALTIME_TRADES_QUOTES

    @property
    def execution_reference_classification(self) -> str:
        if self == MassiveDataMode.DELAYED_TRADES:
            return "NOT_ELIGIBLE_FOR_LIVE_EXECUTION_REFERENCE"
        return "REALTIME_NBBO_EXECUTION_REFERENCE"


@dataclass(frozen=True)
class MassiveStreamStatus:
    mode: MassiveDataMode
    connected: bool
    authenticated: bool
    subscribed: bool
    requested_symbols: tuple[str, ...]
    requested_subscriptions: tuple[str, ...]
    accepted_subscriptions: tuple[str, ...]
    rejected_subscriptions: tuple[str, ...]
    messages_received: int
    trades_received: int
    quotes_received: int
    control_messages_received: int
    malformed_messages: int
    reconnect_count: int
    dropped_messages: int
    endpoint: str
    coverage_classification: str
    evidence_classification: str
    quote_entitlement: bool
    execution_reference_eligible: bool
    execution_reference_classification: str
    last_error: str | None = None


@dataclass(frozen=True)
class LatencyStatistics:
    count: int
    minimum_ms: float | None
    mean_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    maximum_ms: float | None
    invalid_samples: int


@dataclass(frozen=True)
class CapacityStatistics:
    messages_per_second: tuple[tuple[str, int], ...]
    peak_messages_per_second: int
    handler_count: int
    mean_handler_processing_ms: float | None
    maximum_handler_processing_ms: float | None
    queue_depth: int
    dropped_messages: int
    malformed_messages: int


def massive_credential_present(
    environment: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if environment is None else environment
    return bool(source.get(MASSIVE_API_KEY, "").strip())


def parse_massive_sip_timestamp(value: object) -> datetime:
    """Convert Massive's Unix-millisecond SIP timestamp to UTC."""

    if isinstance(value, bool):
        raise ValueError("Massive SIP timestamp must be Unix milliseconds")
    try:
        milliseconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Massive SIP timestamp must be Unix milliseconds") from exc
    if not isfinite(milliseconds) or milliseconds <= 0:
        raise ValueError("Massive SIP timestamp must be positive and finite")
    try:
        return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Massive SIP timestamp is outside the supported range") from exc


def _event_type(message: Mapping[str, Any]) -> str:
    return str(message.get("ev", message.get("T", ""))).strip()


def _safe_diagnostic_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if isinstance(value, str):
        return value[:120]
    if isinstance(value, (list, tuple)):
        return [_safe_diagnostic_value(item) for item in value[:10]]
    return f"<{type(value).__name__}>"


def _safe_market_data_fields(message: Mapping[str, Any]) -> dict[str, object]:
    return {
        field: _safe_diagnostic_value(message[field])
        for field in _SAFE_MARKET_DATA_FIELDS
        if field in message
    }


def _payload_descriptor(payload: object) -> str:
    try:
        length = len(payload)  # type: ignore[arg-type]
    except TypeError:
        return f"<{type(payload).__name__}>"
    return f"<{type(payload).__name__} length={length}>"


def _validate_numeric_field(
    message: Mapping[str, Any],
    field: str,
    classification: MassiveMessageClassification,
    *,
    positive: bool,
) -> None:
    value = message.get(field)
    label = (
        "price"
        if classification == MassiveMessageClassification.MISSING_OR_INVALID_PRICE
        else "size"
    )
    if field not in message:
        raise _MessageValidationError(
            classification,
            field=field,
            value="<missing>",
            reason_key=f"{label}_missing",
            reason=f"required {label} field {field} is missing",
        )
    if isinstance(value, bool):
        valid = False
    else:
        try:
            number = float(value)
            valid = isfinite(number) and (number > 0 if positive else number >= 0)
        except (TypeError, ValueError):
            valid = False
    if not valid:
        requirement = "positive and finite" if positive else "non-negative and finite"
        raise _MessageValidationError(
            classification,
            field=field,
            value=value,
            reason_key=f"{label}_invalid",
            reason=f"{field} must be {requirement}",
        )


def _effective_trade_quantity(
    message: Mapping[str, Any],
) -> tuple[Decimal, str]:
    field = "ds" if "ds" in message else "s"
    label = "decimal_size" if field == "ds" else "size"
    if field not in message:
        raise _MessageValidationError(
            MassiveMessageClassification.MISSING_OR_INVALID_SIZE,
            field=field,
            value="<missing>",
            reason_key=f"{label}_missing",
            reason=f"required trade quantity field {field} is missing",
        )
    value = message.get(field)
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        quantity = Decimal("NaN")
    if not quantity.is_finite() or quantity <= 0:
        raise _MessageValidationError(
            MassiveMessageClassification.MISSING_OR_INVALID_SIZE,
            field=field,
            value=value,
            reason_key=f"{label}_invalid",
            reason=f"{field} must be positive and finite",
        )
    return quantity, field


def _trade_conditions(message: Mapping[str, Any]) -> tuple[str, ...]:
    raw_conditions = message.get("c")
    if raw_conditions is None:
        return ()
    if not isinstance(raw_conditions, (list, tuple)):
        raise TypeError("Massive trade conditions must be an array")
    return tuple(str(item) for item in raw_conditions)


def _trade_eligibility(conditions: tuple[str, ...]) -> _TradeEligibility:
    rules: list[_ConditionUpdateRule] = []
    unresolved: list[str] = []
    for condition in conditions:
        rule = _MASSIVE_SAMPLE_CONDITION_RULES.get(condition)
        if rule is None:
            unresolved.append(condition)
        else:
            rules.append(rule)
    if unresolved:
        return _TradeEligibility(False, False, False, tuple(unresolved))
    if not rules:
        return _TradeEligibility(True, True, True, ())
    return _TradeEligibility(
        updates_high_low=all(rule.updates_high_low for rule in rules),
        updates_open_close=all(rule.updates_open_close for rule in rules),
        updates_volume=all(rule.updates_volume for rule in rules),
        unresolved_conditions=(),
    )


def _validate_market_message(
    message: Mapping[str, Any],
    event_type: str,
) -> tuple[Decimal, str] | None:
    symbol = message.get("sym")
    if "sym" not in message:
        raise _MessageValidationError(
            MassiveMessageClassification.MISSING_OR_INVALID_SYMBOL,
            field="sym",
            value="<missing>",
            reason_key="symbol_missing",
            reason="required symbol field sym is missing",
        )
    if not isinstance(symbol, str) or not symbol.strip():
        raise _MessageValidationError(
            MassiveMessageClassification.MISSING_OR_INVALID_SYMBOL,
            field="sym",
            value=symbol,
            reason_key="symbol_invalid",
            reason="sym must be a non-empty string",
        )

    timestamp = message.get("t")
    if "t" not in message:
        raise _MessageValidationError(
            MassiveMessageClassification.MISSING_OR_INVALID_TIMESTAMP,
            field="t",
            value="<missing>",
            reason_key="timestamp_missing",
            reason="required SIP timestamp field t is missing",
        )
    try:
        parse_massive_sip_timestamp(timestamp)
    except ValueError as exc:
        raise _MessageValidationError(
            MassiveMessageClassification.MISSING_OR_INVALID_TIMESTAMP,
            field="t",
            value=timestamp,
            reason_key="timestamp_invalid",
            reason=str(exc),
        ) from exc

    if event_type == "T":
        _validate_numeric_field(
            message,
            "p",
            MassiveMessageClassification.MISSING_OR_INVALID_PRICE,
            positive=True,
        )
        return _effective_trade_quantity(message)

    for field in ("bp", "ap"):
        _validate_numeric_field(
            message,
            field,
            MassiveMessageClassification.MISSING_OR_INVALID_PRICE,
            positive=True,
        )
    for field in ("bs", "as"):
        _validate_numeric_field(
            message,
            field,
            MassiveMessageClassification.MISSING_OR_INVALID_SIZE,
            positive=False,
        )
    return None


def normalize_massive_message(
    message: Mapping[str, Any],
    *,
    received_at: datetime | None = None,
    _validated_trade_quantity: tuple[Decimal, str] | None = None,
) -> LiveTrade | LiveQuote | None:
    """Normalize Massive T/Q messages and leave status messages separate."""

    event_type = _event_type(message)
    if event_type not in ("T", "Q"):
        return None
    observed_at = system_clock.now() if received_at is None else received_at
    source_timestamp = parse_massive_sip_timestamp(message.get("t"))
    if event_type == "T":
        quantity, quantity_source = (
            _validated_trade_quantity
            if _validated_trade_quantity is not None
            else _effective_trade_quantity(message)
        )
        conditions = _trade_conditions(message)
        eligibility = _trade_eligibility(conditions)
        return LiveTrade(
            symbol=message.get("sym", ""),
            price=message.get("p"),
            size=float(quantity),
            exchange=message.get("x"),
            trade_id=message.get("i"),
            conditions=conditions,
            source_timestamp=source_timestamp,
            received_at=observed_at,
            source="massive",
            created_at=observed_at,
            _metadata={
                "provider_message_type": "trade",
                "provider_sequence": message.get("q"),
                "participant_timestamp": message.get("pt"),
                "tape": message.get("z"),
                "conditions": conditions,
                "provider_size_present": "s" in message,
                "provider_size": message.get("s"),
                "provider_decimal_size_present": "ds" in message,
                "provider_decimal_size": message.get("ds"),
                "effective_quantity_source": quantity_source,
                "effective_quantity_decimal": str(quantity),
                "updates_high_low": eligibility.updates_high_low,
                "updates_open_close": eligibility.updates_open_close,
                "updates_volume": eligibility.updates_volume,
                "unresolved_conditions": eligibility.unresolved_conditions,
            },
        )
    quote_condition = message.get("c")
    indicators = tuple(str(item) for item in (message.get("i") or ()))
    return LiveQuote(
        symbol=message.get("sym", ""),
        bid_price=message.get("bp"),
        bid_size=message.get("bs"),
        bid_exchange=message.get("bx"),
        ask_price=message.get("ap"),
        ask_size=message.get("as"),
        ask_exchange=message.get("ax"),
        source_timestamp=source_timestamp,
        received_at=observed_at,
        source="massive",
        created_at=observed_at,
        _metadata={
            "provider_message_type": "quote",
            "provider_sequence": message.get("q"),
            "tape": message.get("z"),
            "condition": quote_condition,
            "indicators": indicators,
        },
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, ceil(percentile * len(ordered)))
    return ordered[rank - 1]


class MassiveStockStreamAdapter:
    """Authenticate, subscribe, normalize, meter, and deliver Massive data."""

    def __init__(
        self,
        *,
        symbols: tuple[str, ...],
        observation_sink: Callable[[LiveTrade | LiveQuote], object],
        api_key: str,
        mode: MassiveDataMode | str = MassiveDataMode.DELAYED_TRADES,
        endpoint: str | None = None,
        max_attempts: int = 2,
        reconnect_delay_seconds: float = 1.0,
        connect_factory: Callable[..., Any] = connect,
    ) -> None:
        requested = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        )
        if not requested:
            raise ValueError("Massive watchlist requires at least one symbol")
        if len(requested) > MAX_MASSIVE_SYMBOLS:
            raise ValueError(
                f"Massive watchlist cannot exceed {MAX_MASSIVE_SYMBOLS} symbols"
            )
        if any("*" in symbol for symbol in requested):
            raise ValueError("wildcard Massive subscriptions are prohibited")
        selected_mode = MassiveDataMode.parse(mode)
        selected_endpoint = selected_mode.endpoint if endpoint is None else endpoint.strip()
        if not selected_endpoint.lower().startswith("wss://"):
            raise ValueError("Massive endpoint must use wss://")
        if max_attempts <= 0 or max_attempts > 3:
            raise ValueError("max_attempts must be between one and three")
        if reconnect_delay_seconds < 0 or reconnect_delay_seconds > 5:
            raise ValueError("reconnect delay must be between zero and five seconds")
        topics = [f"T.{symbol}" for symbol in requested]
        if selected_mode == MassiveDataMode.REALTIME_TRADES_QUOTES:
            topics.extend(f"Q.{symbol}" for symbol in requested)
        self._symbols = requested
        self._topics = tuple(topics)
        self._mode = selected_mode
        self._observation_sink = observation_sink
        self._api_key = api_key
        self._endpoint = selected_endpoint
        self._max_attempts = max_attempts
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._connect_factory = connect_factory
        self._latencies_ms: list[float] = []
        self._invalid_latency_samples = 0
        self._message_buckets: dict[str, int] = {}
        self._handler_times_ms: list[float] = []
        self._classification_counts = {
            classification: 0 for classification in MassiveMessageClassification
        }
        self._diagnostic_samples: dict[str, list[dict[str, object]]] = {}
        self._delivery_failures = 0
        self._status = MassiveStreamStatus(
            mode=selected_mode,
            connected=False,
            authenticated=False,
            subscribed=False,
            requested_symbols=requested,
            requested_subscriptions=self._topics,
            accepted_subscriptions=(),
            rejected_subscriptions=(),
            messages_received=0,
            trades_received=0,
            quotes_received=0,
            control_messages_received=0,
            malformed_messages=0,
            reconnect_count=0,
            dropped_messages=0,
            endpoint=self._endpoint,
            coverage_classification=selected_mode.coverage_classification,
            evidence_classification=selected_mode.evidence_classification,
            quote_entitlement=selected_mode.quote_entitlement,
            execution_reference_eligible=(
                selected_mode.execution_reference_eligible
            ),
            execution_reference_classification=(
                selected_mode.execution_reference_classification
            ),
        )

    @classmethod
    def from_environment(
        cls,
        *,
        symbols: tuple[str, ...],
        observation_sink: Callable[[LiveTrade | LiveQuote], object],
        environment: Mapping[str, str] | None = None,
        mode: MassiveDataMode | str | None = None,
        max_attempts: int = 2,
        reconnect_delay_seconds: float = 1.0,
        connect_factory: Callable[..., Any] = connect,
    ) -> "MassiveStockStreamAdapter":
        source = os.environ if environment is None else environment
        if not massive_credential_present(source):
            raise MissingMassiveCredentialError("MASSIVE_API_KEY is required")
        selected_mode = MassiveDataMode.parse(
            source.get(MASSIVE_DATA_MODE, MassiveDataMode.DELAYED_TRADES.value)
            if mode is None
            else mode
        )
        return cls(
            symbols=symbols,
            observation_sink=observation_sink,
            api_key=source[MASSIVE_API_KEY],
            mode=selected_mode,
            endpoint=source.get(MASSIVE_WS_URL) or selected_mode.endpoint,
            max_attempts=max_attempts,
            reconnect_delay_seconds=reconnect_delay_seconds,
            connect_factory=connect_factory,
        )

    def __repr__(self) -> str:
        return (
            f"MassiveStockStreamAdapter(mode={self._mode.name}, "
            f"symbols={self._symbols!r}, "
            f"status={self._status!r})"
        )

    @property
    def status(self) -> MassiveStreamStatus:
        return self._status

    @property
    def latency_statistics(self) -> LatencyStatistics:
        values = self._latencies_ms
        return LatencyStatistics(
            count=len(values),
            minimum_ms=None if not values else min(values),
            mean_ms=None if not values else sum(values) / len(values),
            p50_ms=_percentile(values, 0.50),
            p95_ms=_percentile(values, 0.95),
            maximum_ms=None if not values else max(values),
            invalid_samples=self._invalid_latency_samples,
        )

    @property
    def capacity_statistics(self) -> CapacityStatistics:
        buckets = tuple(sorted(self._message_buckets.items()))
        timings = self._handler_times_ms
        return CapacityStatistics(
            messages_per_second=buckets,
            peak_messages_per_second=max((count for _, count in buckets), default=0),
            handler_count=len(timings),
            mean_handler_processing_ms=(
                None if not timings else sum(timings) / len(timings)
            ),
            maximum_handler_processing_ms=None if not timings else max(timings),
            queue_depth=0,
            dropped_messages=self._status.dropped_messages,
            malformed_messages=self._status.malformed_messages,
        )

    @property
    def message_diagnostics(self) -> MassiveMessageDiagnostics:
        counts = tuple(
            (classification.value, self._classification_counts[classification])
            for classification in MassiveMessageClassification
        )
        total = sum(count for _, count in counts)
        malformed_total = sum(
            self._classification_counts[classification]
            for classification in _MALFORMED_CLASSIFICATIONS
        )
        return MassiveMessageDiagnostics(
            messages_received=self._status.messages_received,
            total_classified=total,
            counts_reconcile=total == self._status.messages_received,
            classification_counts=counts,
            malformed_classified=malformed_total,
            malformed_counts_reconcile=(
                malformed_total == self._status.malformed_messages
            ),
            delivery_failures=self._delivery_failures,
            captured_samples=sum(
                len(samples) for samples in self._diagnostic_samples.values()
            ),
        )

    def diagnostic_report(self) -> dict[str, object]:
        diagnostics = self.message_diagnostics
        return {
            "schema_version": 1,
            "generated_at": system_clock.now().isoformat(),
            "provider": "massive",
            "mode": self._mode.name,
            "endpoint": self._endpoint,
            "requested_symbols": list(self._symbols),
            "messages_received": diagnostics.messages_received,
            "total_classified": diagnostics.total_classified,
            "counts_reconcile": diagnostics.counts_reconcile,
            "classification_counts": dict(diagnostics.classification_counts),
            "malformed_messages": self._status.malformed_messages,
            "malformed_classified": diagnostics.malformed_classified,
            "malformed_counts_reconcile": diagnostics.malformed_counts_reconcile,
            "delivery_failures": diagnostics.delivery_failures,
            "exclusion_impact_definitions": {
                "intentionally_ignored_documented": {
                    "bar_ohlc": "NO",
                    "bar_volume": "NO",
                    "reason": "Documented non-T/Q feeds are outside the trade-derived bar path.",
                },
                "unknown_event_type": {
                    "bar_ohlc": "UNCONFIRMED",
                    "bar_volume": "UNCONFIRMED",
                    "reason": "The event schema is unknown until a sanitized sample is reviewed.",
                },
                "invalid_json_or_payload_structure": {
                    "bar_ohlc": "UNCONFIRMED",
                    "bar_volume": "UNCONFIRMED",
                    "reason": "An unreadable payload may contain market events.",
                },
                "missing_or_invalid_symbol": {
                    "bar_ohlc": "POSSIBLE",
                    "bar_volume": "POSSIBLE",
                    "reason": "A rejected trade cannot be assigned to a symbol bar.",
                },
                "missing_or_invalid_timestamp": {
                    "bar_ohlc": "POSSIBLE",
                    "bar_volume": "POSSIBLE",
                    "reason": "A rejected trade cannot be assigned to a bar interval.",
                },
                "missing_or_invalid_price": {
                    "bar_ohlc": "POSSIBLE",
                    "bar_volume": "POSSIBLE",
                    "reason": "The entire event is rejected when its price is invalid.",
                },
                "missing_or_invalid_size": {
                    "bar_ohlc": "POSSIBLE",
                    "bar_volume": "POSSIBLE",
                    "reason": "The entire event is rejected when its size is invalid.",
                },
                "other_domain_validation_failure": {
                    "bar_ohlc": "POSSIBLE",
                    "bar_volume": "POSSIBLE",
                    "reason": "A rejected trade cannot enter a completed bar.",
                },
                "delivery_failure": {
                    "bar_ohlc": "YES_FOR_TRADES",
                    "bar_volume": "YES_FOR_TRADES",
                    "reason": "A normalized trade that is not delivered cannot reach the bar builder.",
                },
            },
            "samples_by_reason": {
                reason: list(samples)
                for reason, samples in sorted(self._diagnostic_samples.items())
            },
        }

    def write_diagnostic_report(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.diagnostic_report(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    def _authentication_message(self) -> dict[str, str]:
        return {"action": "auth", "params": self._api_key}

    def subscription_message(self) -> dict[str, str]:
        return {"action": "subscribe", "params": ",".join(self._topics)}

    def _record_message_arrival(self, received_at: datetime) -> None:
        bucket = received_at.replace(microsecond=0).isoformat()
        self._message_buckets[bucket] = self._message_buckets.get(bucket, 0) + 1
        self._status = replace(
            self._status,
            messages_received=self._status.messages_received + 1,
        )

    def _record_primary_classification(
        self,
        classification: MassiveMessageClassification,
    ) -> None:
        self._classification_counts[classification] += 1

    def _capture_diagnostic_sample(
        self,
        *,
        reason_key: str,
        classification: MassiveMessageClassification | str,
        event_type: str,
        message: Mapping[str, Any],
        offending_field: str,
        offending_value: object,
        validation_reason: str,
        delivery_failure: bool = False,
    ) -> None:
        samples = self._diagnostic_samples.setdefault(reason_key, [])
        if len(samples) >= MAX_DIAGNOSTIC_SAMPLES_PER_REASON:
            return
        if event_type == "T":
            impact = "YES" if delivery_failure else "POSSIBLE"
        elif event_type == "Q" or event_type in DOCUMENTED_IGNORED_EVENT_TYPES:
            impact = "NO"
        else:
            impact = "UNCONFIRMED"
        samples.append(
            {
                "classification": (
                    classification.value
                    if isinstance(classification, MassiveMessageClassification)
                    else str(classification)
                ),
                "event_type": event_type or "<missing>",
                "safe_market_data_fields": _safe_market_data_fields(message),
                "offending_field": offending_field,
                "offending_value": _safe_diagnostic_value(offending_value),
                "validation_reason": validation_reason[:240],
                "bar_ohlc_impact": impact,
                "bar_volume_impact": impact,
            }
        )

    def _record_rejection_or_ignored(
        self,
        classification: MassiveMessageClassification,
        *,
        reason_key: str,
        event_type: str,
        message: Mapping[str, Any],
        offending_field: str,
        offending_value: object,
        validation_reason: str,
    ) -> None:
        self._record_primary_classification(classification)
        self._capture_diagnostic_sample(
            reason_key=reason_key,
            classification=classification,
            event_type=event_type,
            message=message,
            offending_field=offending_field,
            offending_value=offending_value,
            validation_reason=validation_reason,
        )
        if classification in _MALFORMED_CLASSIFICATIONS:
            self._status = replace(
                self._status,
                malformed_messages=self._status.malformed_messages + 1,
                last_error=f"Massive message rejected: {classification.value}",
            )

    def _record_payload_rejection(
        self,
        *,
        reason_key: str,
        payload: object,
        validation_reason: str,
    ) -> None:
        handler_start = system_clock.monotonic()
        self._record_message_arrival(system_clock.now())
        try:
            self._record_rejection_or_ignored(
                MassiveMessageClassification.INVALID_JSON_OR_PAYLOAD_STRUCTURE,
                reason_key=reason_key,
                event_type="",
                message={},
                offending_field="payload",
                offending_value=_payload_descriptor(payload),
                validation_reason=validation_reason,
            )
        finally:
            elapsed_ms = max(
                0.0,
                (system_clock.monotonic() - handler_start) * 1000.0,
            )
            self._handler_times_ms.append(elapsed_ms)

    def handle_message(self, message: Mapping[str, Any]) -> LiveTrade | LiveQuote | None:
        """Separate controls, normalize market data, and record bounded metrics."""

        handler_start = system_clock.monotonic()
        received_at = system_clock.now()
        self._record_message_arrival(received_at)
        try:
            event_type = _event_type(message)
            if event_type.lower() == "status":
                self._handle_control(message)
                self._record_primary_classification(
                    MassiveMessageClassification.RECOGNIZED_CONTROL
                )
                return None
            if event_type in DOCUMENTED_IGNORED_EVENT_TYPES:
                self._record_rejection_or_ignored(
                    MassiveMessageClassification.INTENTIONALLY_IGNORED_DOCUMENTED,
                    reason_key=f"documented_event_type_{event_type}",
                    event_type=event_type,
                    message=message,
                    offending_field="ev",
                    offending_value=event_type,
                    validation_reason=(
                        f"documented Massive {event_type} feed is outside the "
                        "subscribed T/Q ingestion contract"
                    ),
                )
                return None
            if event_type not in ("T", "Q"):
                self._record_rejection_or_ignored(
                    MassiveMessageClassification.UNKNOWN_EVENT_TYPE,
                    reason_key="unknown_event_type",
                    event_type=event_type,
                    message=message,
                    offending_field="ev",
                    offending_value=event_type or "<missing>",
                    validation_reason="event type is not recognized by the Massive adapter",
                )
                return None
            try:
                validated_quantity = _validate_market_message(message, event_type)
                observation = normalize_massive_message(
                    message,
                    received_at=received_at,
                    _validated_trade_quantity=validated_quantity,
                )
            except _MessageValidationError as exc:
                self._record_rejection_or_ignored(
                    exc.classification,
                    reason_key=exc.reason_key,
                    event_type=event_type,
                    message=message,
                    offending_field=exc.field,
                    offending_value=exc.value,
                    validation_reason=exc.reason,
                )
                return None
            except (TypeError, ValueError) as exc:
                self._record_rejection_or_ignored(
                    MassiveMessageClassification.OTHER_DOMAIN_VALIDATION_FAILURE,
                    reason_key="domain_validation_failure",
                    event_type=event_type,
                    message=message,
                    offending_field="domain_object",
                    offending_value="<validation failed>",
                    validation_reason=f"{type(exc).__name__}: {exc}",
                )
                return None
            if observation is None:
                self._record_rejection_or_ignored(
                    MassiveMessageClassification.OTHER_DOMAIN_VALIDATION_FAILURE,
                    reason_key="normalizer_returned_none",
                    event_type=event_type,
                    message=message,
                    offending_field="normalizer",
                    offending_value="None",
                    validation_reason="recognized market event produced no observation",
                )
                return None
            self._record_latency(observation)
            if isinstance(observation, LiveTrade):
                self._record_primary_classification(
                    MassiveMessageClassification.ACCEPTED_TRADE
                )
                self._status = replace(
                    self._status,
                    trades_received=self._status.trades_received + 1,
                )
            else:
                self._record_primary_classification(
                    MassiveMessageClassification.ACCEPTED_QUOTE
                )
                self._status = replace(
                    self._status,
                    quotes_received=self._status.quotes_received + 1,
                )
            try:
                self._observation_sink(observation)
            except Exception:
                self._delivery_failures += 1
                self._capture_diagnostic_sample(
                    reason_key="delivery_failure",
                    classification="delivery_failure",
                    event_type=event_type,
                    message=message,
                    offending_field="observation_sink",
                    offending_value="<exception details omitted>",
                    validation_reason="normalized observation delivery raised an exception",
                    delivery_failure=True,
                )
                self._status = replace(
                    self._status,
                    dropped_messages=self._status.dropped_messages + 1,
                    last_error="Normalized observation delivery failed",
                )
                raise
            return observation
        finally:
            elapsed_ms = max(0.0, (system_clock.monotonic() - handler_start) * 1000.0)
            self._handler_times_ms.append(elapsed_ms)

    def handle_payload(self, payload: str | bytes) -> tuple[LiveTrade | LiveQuote, ...]:
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError):
            self._record_payload_rejection(
                reason_key="invalid_json",
                payload=payload,
                validation_reason="payload is not valid JSON",
            )
            return ()
        if isinstance(decoded, list):
            if not decoded:
                self._record_payload_rejection(
                    reason_key="empty_payload_array",
                    payload=decoded,
                    validation_reason="payload array contains no message entries",
                )
                return ()
            messages = decoded
        elif isinstance(decoded, Mapping):
            messages = [decoded]
        else:
            self._record_payload_rejection(
                reason_key="payload_not_object_or_array",
                payload=decoded,
                validation_reason="decoded payload must be an object or array of objects",
            )
            return ()
        observations: list[LiveTrade | LiveQuote] = []
        for message in messages:
            if not isinstance(message, Mapping):
                self._record_payload_rejection(
                    reason_key="payload_entry_not_object",
                    payload=message,
                    validation_reason="payload array entry must be an object",
                )
                continue
            observation = self.handle_message(message)
            if observation is not None:
                observations.append(observation)
        return tuple(observations)

    async def run(self, *, max_seconds: float = 180.0) -> tuple[LiveTrade | LiveQuote, ...]:
        if not self._api_key.strip():
            raise MissingMassiveCredentialError("MASSIVE_API_KEY is required")
        if max_seconds <= 0 or max_seconds > 600:
            raise ValueError("max_seconds must be between zero and 600")
        observations: list[LiveTrade | LiveQuote] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_seconds
        for attempt in range(1, self._max_attempts + 1):
            self._status = replace(
                self._status,
                connected=False,
                authenticated=False,
                subscribed=False,
                reconnect_count=attempt - 1,
                last_error=None,
            )
            try:
                async with self._connect_factory(
                    self._endpoint,
                    open_timeout=10,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    self._status = replace(self._status, connected=True)
                    await websocket.send(json.dumps(self._authentication_message()))
                    await self._receive_until(
                        websocket,
                        deadline,
                        "authenticated",
                        observations,
                    )
                    await websocket.send(json.dumps(self.subscription_message()))
                    await self._receive_until(
                        websocket,
                        deadline,
                        "subscribed",
                        observations,
                    )
                    while loop.time() < deadline:
                        remaining = deadline - loop.time()
                        payload = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=remaining,
                        )
                        observations.extend(self.handle_payload(payload))
                    return tuple(observations)
            except asyncio.CancelledError:
                self._status = replace(
                    self._status,
                    last_error="CancelledError: stream cancelled",
                )
                raise
            except TimeoutError:
                if self._status.subscribed:
                    return tuple(observations)
                self._status = replace(
                    self._status,
                    last_error="TimeoutError: stream deadline reached",
                )
            except Exception as exc:
                self._status = replace(
                    self._status,
                    last_error=f"{type(exc).__name__}: connection attempt failed",
                )
            finally:
                self._status = replace(self._status, connected=False)
            if attempt < self._max_attempts and loop.time() < deadline:
                await asyncio.sleep(
                    min(
                        self._reconnect_delay_seconds,
                        max(0.0, deadline - loop.time()),
                    )
                )
        return tuple(observations)

    async def _receive_until(
        self,
        websocket: Any,
        deadline: float,
        status_field: str,
        observations: list[LiveTrade | LiveQuote],
    ) -> None:
        loop = asyncio.get_running_loop()
        while not getattr(self._status, status_field):
            remaining = min(10.0, deadline - loop.time())
            if remaining <= 0:
                raise TimeoutError
            payload = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            observations.extend(self.handle_payload(payload))
            if self._status.last_error is not None:
                raise RuntimeError("Massive rejected authentication or subscription")

    def _handle_control(self, message: Mapping[str, Any]) -> None:
        status = str(message.get("status", "")).strip().lower()
        text = str(message.get("message", "")).strip().lower()
        self._status = replace(
            self._status,
            control_messages_received=self._status.control_messages_received + 1,
        )
        if status in ("auth_success", "authenticated") or "authenticated" in text:
            self._status = replace(self._status, authenticated=True)
            return
        if status in ("success", "subscribed") and "subscrib" in text:
            mentioned = tuple(topic for topic in self._topics if topic.lower() in text)
            acknowledged = mentioned or self._topics
            accepted_set = set(self._status.accepted_subscriptions) | set(acknowledged)
            accepted = tuple(topic for topic in self._topics if topic in accepted_set)
            rejected = tuple(topic for topic in self._topics if topic not in accepted)
            self._status = replace(
                self._status,
                subscribed=set(accepted) == set(self._topics),
                accepted_subscriptions=accepted,
                rejected_subscriptions=rejected,
            )
            return
        if status in ("auth_failed", "error", "failed"):
            self._status = replace(
                self._status,
                rejected_subscriptions=tuple(
                    topic
                    for topic in self._topics
                    if topic not in self._status.accepted_subscriptions
                ),
                last_error=f"Massive status error: {status or 'unknown'}",
            )

    def _record_latency(self, observation: LiveTrade | LiveQuote) -> None:
        latency_ms = (
            observation.received_at - observation.source_timestamp
        ).total_seconds() * 1000.0
        if not isfinite(latency_ms) or latency_ms < 0:
            self._invalid_latency_samples += 1
            return
        self._latencies_ms.append(latency_ms)
