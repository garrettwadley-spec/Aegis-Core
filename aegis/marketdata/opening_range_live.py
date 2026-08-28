"""Five-minute opening-range and evaluation-window materialization."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aegis.clock import system_clock
from aegis.clock.utc import ensure_utc
from aegis.eventbus import Event, EventBus, Subscriber

from .live_bars import THIRTY_SECOND_BAR_CLOSED
from .live_models import OpeningRangeState, ThirtySecondBar


OPENING_RANGE_COMPLETED = "OpeningRangeCompleted"
MARKET_TIMEZONE = ZoneInfo("America/New_York")
OPENING_START = time(9, 30)
OPENING_END = time(9, 35)
EVALUATION_END = time(10, 0)
EXPECTED_OPENING_BARS = 10


class OpeningRangeBuilder(Subscriber):
    """Collect completed bars into the 09:30-09:35 ET opening range."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._opening_bars: dict[
            tuple[str, date], list[tuple[int, ThirtySecondBar]]
        ] = {}
        self._ranges: dict[tuple[str, date], OpeningRangeState] = {}
        self._evaluation_bars: list[ThirtySecondBar] = []
        event_bus.subscribe(THIRTY_SECOND_BAR_CLOSED, self)

    @property
    def ranges(self) -> tuple[OpeningRangeState, ...]:
        return tuple(self._ranges[key] for key in sorted(self._ranges))

    @property
    def evaluation_bars(self) -> tuple[ThirtySecondBar, ...]:
        return tuple(self._evaluation_bars)

    def receive(self, event: Event) -> None:
        if event.event_type != THIRTY_SECOND_BAR_CLOSED:
            raise ValueError("opening range accepts ThirtySecondBarClosed only")
        if event.sequence_number is None:
            raise ValueError("closed bar event requires a sequence number")
        if not isinstance(event.payload, ThirtySecondBar):
            raise TypeError("ThirtySecondBarClosed payload must be ThirtySecondBar")

        bar = event.payload
        local_start = bar.interval_start.astimezone(MARKET_TIMEZONE)
        local_end = bar.interval_end.astimezone(MARKET_TIMEZONE)
        key = (bar.symbol, local_start.date())
        if key in self._ranges:
            if OPENING_END <= local_start.time() < EVALUATION_END:
                self._evaluation_bars.append(bar)
            return
        if local_start.time() >= OPENING_END:
            self._finalize(key)

        if (
            local_start.time() >= OPENING_START
            and local_end.time() <= OPENING_END
            and local_start.date() == local_end.date()
        ):
            entries = self._opening_bars.setdefault(key, [])
            if all(existing.object_id != bar.object_id for _, existing in entries):
                entries.append((event.sequence_number, bar))
                entries.sort(key=lambda item: item[1].interval_start)
            return

        if OPENING_END <= local_start.time() < EVALUATION_END:
            self._evaluation_bars.append(bar)

    def advance(self, symbol: str, through_timestamp: datetime) -> OpeningRangeState | None:
        local = ensure_utc(through_timestamp).astimezone(MARKET_TIMEZONE)
        if local.time() < OPENING_END:
            return None
        return self._finalize((symbol.strip().upper(), local.date()))

    def _finalize(self, key: tuple[str, date]) -> OpeningRangeState | None:
        existing = self._ranges.get(key)
        if existing is not None:
            return existing
        entries = self._opening_bars.get(key, [])
        if not entries:
            return None
        bars = [bar for _, bar in entries]
        local_window_start = datetime.combine(
            key[1], OPENING_START, tzinfo=MARKET_TIMEZONE
        )
        local_window_end = datetime.combine(
            key[1], OPENING_END, tzinfo=MARKET_TIMEZONE
        )
        expected_starts = {
            (local_window_start + timedelta(seconds=30 * index)).astimezone(
                bars[0].interval_start.tzinfo
            )
            for index in range(EXPECTED_OPENING_BARS)
        }
        actual_starts = {bar.interval_start for bar in bars}
        state = OpeningRangeState(
            symbol=key[0],
            session_date=key[1],
            window_start=local_window_start,
            window_end=local_window_end,
            range_open=bars[0].open,
            range_high=max(bar.high for bar in bars),
            range_low=min(bar.low for bar in bars),
            range_close=bars[-1].close,
            total_volume=sum(bar.volume for bar in bars),
            completed_bar_count=len(bars),
            source_bar_ids=tuple(bar.object_id for bar in bars),
            source_event_sequences=tuple(sequence for sequence, _ in entries),
            complete=(
                len(bars) == EXPECTED_OPENING_BARS
                and actual_starts == expected_starts
            ),
            created_at=system_clock.now(),
            trace_id=bars[0].trace_id,
            correlation_id=bars[0].correlation_id,
            _metadata={"market_timezone": str(MARKET_TIMEZONE)},
        )
        self._ranges[key] = state
        self._event_bus.publish(
            Event.create(
                OPENING_RANGE_COMPLETED,
                state,
                trace_id=state.trace_id,
                correlation_id=state.correlation_id,
            )
        )
        return state
