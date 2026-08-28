"""Deterministic source-time 30-second trade bar construction."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aegis.clock import system_clock
from aegis.clock.utc import ensure_utc
from aegis.eventbus import Event, EventBus, Subscriber

from .live_bus import LIVE_QUOTE_RECEIVED, LIVE_TRADE_RECEIVED
from .live_models import LiveQuote, LiveTrade, ThirtySecondBar


THIRTY_SECOND_BAR_CLOSED = "ThirtySecondBarClosed"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def interval_for(timestamp: datetime) -> tuple[datetime, datetime]:
    """Return the fixed UTC-aligned 30-second interval containing timestamp."""

    normalized = ensure_utc(timestamp)
    elapsed_seconds = int((normalized - _EPOCH).total_seconds())
    interval_seconds = elapsed_seconds - elapsed_seconds % 30
    start = _EPOCH + timedelta(seconds=interval_seconds)
    return start, start + timedelta(seconds=30)


@dataclass(frozen=True)
class LateTradeRejection:
    symbol: str
    trade_id: str | None
    source_timestamp: datetime
    interval_start: datetime
    interval_end: datetime
    reason: str = "interval_already_closed"


@dataclass
class _ActiveBar:
    symbol: str
    interval_start: datetime
    interval_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    trace_id: str
    correlation_id: str
    source_trade_ids: list[str] = field(default_factory=list)
    source_event_sequences: list[int] = field(default_factory=list)

    def add(self, trade: LiveTrade, event_sequence: int) -> None:
        self.high = max(self.high, trade.price)
        self.low = min(self.low, trade.price)
        self.close = trade.price
        self.volume += trade.size
        self.trade_count += 1
        if trade.trade_id is not None:
            self.source_trade_ids.append(trade.trade_id)
        self.source_event_sequences.append(event_sequence)


class ThirtySecondBarBuilder(Subscriber):
    """Build immutable OHLCV bars without reopening completed history."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._active: dict[tuple[str, datetime], _ActiveBar] = {}
        self._watermarks: dict[str, datetime] = {}
        self._latest_quotes: dict[str, LiveQuote] = {}
        self._bars: list[ThirtySecondBar] = []
        self._late_trade_rejections: list[LateTradeRejection] = []
        event_bus.subscribe(LIVE_TRADE_RECEIVED, self)
        event_bus.subscribe(LIVE_QUOTE_RECEIVED, self)

    @property
    def bars(self) -> tuple[ThirtySecondBar, ...]:
        return tuple(self._bars)

    @property
    def late_trade_rejections(self) -> tuple[LateTradeRejection, ...]:
        return tuple(self._late_trade_rejections)

    def receive(self, event: Event) -> None:
        if event.sequence_number is None:
            raise ValueError("live observation event requires a sequence number")
        if event.event_type == LIVE_TRADE_RECEIVED:
            if not isinstance(event.payload, LiveTrade):
                raise TypeError("LiveTradeReceived payload must be LiveTrade")
            self.process_trade(event.payload, event.sequence_number)
            return
        if event.event_type == LIVE_QUOTE_RECEIVED:
            if not isinstance(event.payload, LiveQuote):
                raise TypeError("LiveQuoteReceived payload must be LiveQuote")
            self.process_quote(event.payload)
            return
        raise ValueError("30-second bar builder received an unsupported event")

    def process_trade(self, trade: LiveTrade, event_sequence: int) -> bool:
        self._advance_watermark(trade.symbol, trade.source_timestamp)
        interval_start, interval_end = interval_for(trade.source_timestamp)
        watermark = self._watermarks.get(trade.symbol)
        if watermark is not None and interval_end <= watermark and trade.source_timestamp < watermark:
            self._late_trade_rejections.append(
                LateTradeRejection(
                    symbol=trade.symbol,
                    trade_id=trade.trade_id,
                    source_timestamp=trade.source_timestamp,
                    interval_start=interval_start,
                    interval_end=interval_end,
                )
            )
            return False

        key = (trade.symbol, interval_start)
        active = self._active.get(key)
        if active is None:
            trade_ids = [] if trade.trade_id is None else [trade.trade_id]
            self._active[key] = _ActiveBar(
                symbol=trade.symbol,
                interval_start=interval_start,
                interval_end=interval_end,
                open=trade.price,
                high=trade.price,
                low=trade.price,
                close=trade.price,
                volume=trade.size,
                trade_count=1,
                trace_id=trade.trace_id,
                correlation_id=trade.correlation_id,
                source_trade_ids=trade_ids,
                source_event_sequences=[event_sequence],
            )
        else:
            active.add(trade, event_sequence)
        return True

    def process_quote(self, quote: LiveQuote) -> None:
        self._advance_watermark(quote.symbol, quote.source_timestamp)
        existing = self._latest_quotes.get(quote.symbol)
        if existing is None or quote.source_timestamp >= existing.source_timestamp:
            self._latest_quotes[quote.symbol] = quote

    def advance(self, symbol: str, through_timestamp: datetime) -> tuple[ThirtySecondBar, ...]:
        """Close source intervals completed at the supplied provider watermark."""

        before = len(self._bars)
        self._advance_watermark(symbol.strip().upper(), ensure_utc(through_timestamp))
        return tuple(self._bars[before:])

    def _advance_watermark(self, symbol: str, timestamp: datetime) -> None:
        current = self._watermarks.get(symbol)
        if current is not None and timestamp <= current:
            return
        closable = sorted(
            (
                key
                for key, active in self._active.items()
                if key[0] == symbol and active.interval_end <= timestamp
            ),
            key=lambda key: key[1],
        )
        for key in closable:
            self._close(self._active.pop(key))
        self._watermarks[symbol] = timestamp

    def _close(self, active: _ActiveBar) -> ThirtySecondBar:
        quote = self._latest_quotes.get(active.symbol)
        bar = ThirtySecondBar(
            symbol=active.symbol,
            interval_start=active.interval_start,
            interval_end=active.interval_end,
            open=active.open,
            high=active.high,
            low=active.low,
            close=active.close,
            volume=active.volume,
            trade_count=active.trade_count,
            latest_bid=None if quote is None else quote.bid_price,
            latest_ask=None if quote is None else quote.ask_price,
            source_trade_ids=tuple(active.source_trade_ids),
            source_event_sequences=tuple(active.source_event_sequences),
            created_at=system_clock.now(),
            trace_id=active.trace_id,
            correlation_id=active.correlation_id,
            _metadata={"bar_price_source": "eligible_trades"},
        )
        self._bars.append(bar)
        self._event_bus.publish(
            Event.create(
                THIRTY_SECOND_BAR_CLOSED,
                bar,
                trace_id=bar.trace_id,
                correlation_id=bar.correlation_id,
            )
        )
        return bar


def completed_bar_signal_price(bar: ThirtySecondBar) -> float:
    """Return the only approved signal reference: the completed bar close."""

    return bar.close


def future_buy_execution_reference(
    latest_quote: LiveQuote | None,
    next_trade: LiveTrade | None = None,
) -> float | None:
    """Prefer current ask, otherwise the next eligible post-signal trade."""

    if latest_quote is not None:
        return latest_quote.ask_price
    return None if next_trade is None else next_trade.price


def future_sell_execution_reference(
    latest_quote: LiveQuote | None,
    next_trade: LiveTrade | None = None,
) -> float | None:
    """Prefer current bid, otherwise the next eligible post-signal trade."""

    if latest_quote is not None:
        return latest_quote.bid_price
    return None if next_trade is None else next_trade.price
