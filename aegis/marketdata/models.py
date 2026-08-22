"""Boundary and canonical market-data models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from aegis.clock import system_clock
from aegis.clock.utc import ensure_utc
from aegis.domain import DomainObject


@dataclass
class RawMarketData:
    """Provider-neutral observation at the ingestion boundary."""

    symbol: str
    exchange: str
    bid: float
    ask: float
    last: float
    volume: float
    source: str
    source_timestamp: datetime | str


@dataclass(frozen=True, kw_only=True)
class MarketData(DomainObject):
    """Immutable canonical market observation."""

    symbol: str
    exchange: str
    bid: float
    ask: float
    last: float
    volume: float
    source: str
    source_timestamp: datetime
    received_at: datetime


def _finite_number(value: float, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _source_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source_timestamp must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source_timestamp must be an ISO 8601 timestamp") from exc
    return ensure_utc(parsed)


def normalize_market_data(raw: RawMarketData) -> MarketData:
    """Validate and normalize one boundary observation."""

    if not isinstance(raw.symbol, str) or not raw.symbol.strip():
        raise ValueError("symbol is required")
    if not isinstance(raw.source, str) or not raw.source.strip():
        raise ValueError("source is required")
    if not isinstance(raw.exchange, str):
        raise ValueError("exchange must be a string")

    bid = _finite_number(raw.bid, "bid")
    ask = _finite_number(raw.ask, "ask")
    last = _finite_number(raw.last, "last")
    volume = _finite_number(raw.volume, "volume")
    if volume < 0:
        raise ValueError("volume cannot be negative")

    received_at = system_clock.now()
    return MarketData(
        symbol=raw.symbol.strip().upper(),
        exchange=raw.exchange.strip().upper(),
        bid=bid,
        ask=ask,
        last=last,
        volume=volume,
        source=raw.source.strip(),
        source_timestamp=_source_timestamp(raw.source_timestamp),
        received_at=received_at,
        created_at=received_at,
    )
