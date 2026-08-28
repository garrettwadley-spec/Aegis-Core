"""Immutable provider-neutral live market observations and aggregates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite

from aegis.clock.utc import ensure_utc
from aegis.domain import DomainObject


def _number(value: float, field_name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{field_name} must be positive")
    if not positive and number < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return number


def _symbol(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("symbol is required")
    return value.strip().upper()


def parse_source_timestamp(value: datetime | str) -> datetime:
    """Parse one provider timestamp and normalize it to timezone-aware UTC."""

    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source_timestamp must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("source_timestamp must be an ISO 8601 timestamp") from exc
    return ensure_utc(parsed)


@dataclass(frozen=True, kw_only=True)
class LiveTrade(DomainObject):
    """One immutable provider-neutral eligible trade."""

    symbol: str
    price: float
    size: float
    source_timestamp: datetime
    received_at: datetime
    source: str
    exchange: str | None = None
    trade_id: str | None = None
    conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source is required")
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "price", _number(self.price, "price", positive=True))
        object.__setattr__(self, "size", _number(self.size, "size", positive=True))
        object.__setattr__(self, "source_timestamp", ensure_utc(self.source_timestamp))
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))
        object.__setattr__(self, "source", self.source.strip().lower())
        if self.exchange is not None:
            object.__setattr__(self, "exchange", str(self.exchange).strip().upper() or None)
        if self.trade_id is not None:
            object.__setattr__(self, "trade_id", str(self.trade_id))
        object.__setattr__(self, "conditions", tuple(str(item) for item in self.conditions))


@dataclass(frozen=True, kw_only=True)
class LiveQuote(DomainObject):
    """One immutable provider-neutral top-of-book quote."""

    symbol: str
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float
    source_timestamp: datetime
    received_at: datetime
    source: str
    bid_exchange: str | None = None
    ask_exchange: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source is required")
        bid = _number(self.bid_price, "bid_price", positive=True)
        ask = _number(self.ask_price, "ask_price", positive=True)
        if ask < bid:
            raise ValueError("ask_price cannot be below bid_price")
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "bid_price", bid)
        object.__setattr__(self, "bid_size", _number(self.bid_size, "bid_size"))
        object.__setattr__(self, "ask_price", ask)
        object.__setattr__(self, "ask_size", _number(self.ask_size, "ask_size"))
        object.__setattr__(self, "source_timestamp", ensure_utc(self.source_timestamp))
        object.__setattr__(self, "received_at", ensure_utc(self.received_at))
        object.__setattr__(self, "source", self.source.strip().lower())
        if self.bid_exchange is not None:
            object.__setattr__(self, "bid_exchange", str(self.bid_exchange).strip().upper() or None)
        if self.ask_exchange is not None:
            object.__setattr__(self, "ask_exchange", str(self.ask_exchange).strip().upper() or None)


@dataclass(frozen=True, kw_only=True)
class ThirtySecondBar(DomainObject):
    """One completed trade-derived 30-second OHLCV interval."""

    symbol: str
    interval_start: datetime
    interval_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    latest_bid: float | None
    latest_ask: float | None
    source_trade_ids: tuple[str, ...]
    source_event_sequences: tuple[int, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        start = ensure_utc(self.interval_start)
        end = ensure_utc(self.interval_end)
        if end - start != timedelta(seconds=30):
            raise ValueError("bar interval must be exactly 30 seconds")
        prices = {
            "open": _number(self.open, "open", positive=True),
            "high": _number(self.high, "high", positive=True),
            "low": _number(self.low, "low", positive=True),
            "close": _number(self.close, "close", positive=True),
        }
        if prices["high"] < max(prices["open"], prices["low"], prices["close"]):
            raise ValueError("bar high is below an OHLC value")
        if prices["low"] > min(prices["open"], prices["high"], prices["close"]):
            raise ValueError("bar low is above an OHLC value")
        if not isinstance(self.trade_count, int) or self.trade_count <= 0:
            raise ValueError("trade_count must be a positive integer")
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "interval_start", start)
        object.__setattr__(self, "interval_end", end)
        for field_name, value in prices.items():
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "volume", _number(self.volume, "volume", positive=True))
        if self.latest_bid is not None:
            object.__setattr__(self, "latest_bid", _number(self.latest_bid, "latest_bid", positive=True))
        if self.latest_ask is not None:
            object.__setattr__(self, "latest_ask", _number(self.latest_ask, "latest_ask", positive=True))
        if self.latest_bid is not None and self.latest_ask is not None and self.latest_ask < self.latest_bid:
            raise ValueError("latest ask cannot be below latest bid")
        object.__setattr__(self, "source_trade_ids", tuple(self.source_trade_ids))
        object.__setattr__(self, "source_event_sequences", tuple(self.source_event_sequences))


@dataclass(frozen=True, kw_only=True)
class OpeningRangeState(DomainObject):
    """Immutable materialization of the first five regular-session minutes."""

    symbol: str
    session_date: date
    window_start: datetime
    window_end: datetime
    range_open: float
    range_high: float
    range_low: float
    range_close: float
    total_volume: float
    completed_bar_count: int
    source_bar_ids: tuple[str, ...]
    source_event_sequences: tuple[int, ...]
    complete: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        start = ensure_utc(self.window_start)
        end = ensure_utc(self.window_end)
        if end - start != timedelta(minutes=5):
            raise ValueError("opening range window must be exactly five minutes")
        prices = (
            _number(self.range_open, "range_open", positive=True),
            _number(self.range_high, "range_high", positive=True),
            _number(self.range_low, "range_low", positive=True),
            _number(self.range_close, "range_close", positive=True),
        )
        if prices[1] < max(prices[0], prices[2], prices[3]):
            raise ValueError("range high is below an OHLC value")
        if prices[2] > min(prices[0], prices[1], prices[3]):
            raise ValueError("range low is above an OHLC value")
        if self.completed_bar_count <= 0:
            raise ValueError("completed_bar_count must be positive")
        object.__setattr__(self, "symbol", _symbol(self.symbol))
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "range_open", prices[0])
        object.__setattr__(self, "range_high", prices[1])
        object.__setattr__(self, "range_low", prices[2])
        object.__setattr__(self, "range_close", prices[3])
        object.__setattr__(self, "total_volume", _number(self.total_volume, "total_volume", positive=True))
        object.__setattr__(self, "source_bar_ids", tuple(self.source_bar_ids))
        object.__setattr__(self, "source_event_sequences", tuple(self.source_event_sequences))
