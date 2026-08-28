"""Run the deterministic offline 30-second live market-data demo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import EventBus
from aegis.marketdata import (
    AlpacaStockStreamAdapter,
    AlpacaStreamMode,
    LiveMarketDataBus,
    LiveQuote,
    LiveTrade,
    OpeningRangeBuilder,
    ThirtySecondBarBuilder,
    completed_bar_signal_price,
    future_buy_execution_reference,
    future_sell_execution_reference,
)


NEW_YORK = ZoneInfo("America/New_York")


def _iso(timestamp: datetime) -> str:
    return timestamp.isoformat().replace("+00:00", "Z")


def main() -> None:
    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2026-01-02T14:30:00+00:00",
        replay_step_seconds=0.001,
        sequence_start=1,
    )
    try:
        event_bus = EventBus()
        live_bus = LiveMarketDataBus(event_bus)
        bar_builder = ThirtySecondBarBuilder(event_bus)
        opening_builder = OpeningRangeBuilder(event_bus)
        observations: list[LiveTrade | LiveQuote] = []
        adapter = AlpacaStockStreamAdapter(
            mode=AlpacaStreamMode.TEST,
            symbols=("FAKEPACA",),
            observation_sink=lambda item: (observations.append(item), live_bus.ingest(item)),
            api_key="offline-demo",
            api_secret="offline-demo",
        )

        start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
        for index in range(12):
            interval_start = start + timedelta(seconds=30 * index)
            base = 10.00 + 0.02 * index
            second_price = base + (0.03 if index % 2 == 0 else -0.02)
            adapter.handle_message(
                {
                    "T": "q",
                    "S": "FAKEPACA",
                    "bx": "V",
                    "bp": round(base - 0.02, 2),
                    "bs": 20,
                    "ax": "V",
                    "ap": round(base + 0.02, 2),
                    "as": 25,
                    "t": _iso(interval_start + timedelta(seconds=1)),
                }
            )
            for offset, price, size, suffix in (
                (5, base, 100, "A"),
                (20, second_price, 50, "B"),
            ):
                adapter.handle_message(
                    {
                        "T": "t",
                        "S": "FAKEPACA",
                        "i": f"T{index + 1:02d}{suffix}",
                        "x": "V",
                        "p": round(price, 2),
                        "s": size,
                        "c": ["@"],
                        "t": _iso(interval_start + timedelta(seconds=offset)),
                    }
                )

        bar_builder.advance("FAKEPACA", start + timedelta(minutes=6))
        event_bus.dispatch()
        opening_builder.advance("FAKEPACA", start + timedelta(minutes=6))
        event_bus.dispatch()

        trades = tuple(item for item in observations if isinstance(item, LiveTrade))
        quotes = tuple(item for item in observations if isinstance(item, LiveQuote))
        print("LIVE OBSERVATIONS")
        print(f"Trades received: {len(trades)}")
        print(f"Quotes received: {len(quotes)}")
        print()
        print("30-SECOND BARS")
        for bar in bar_builder.bars:
            local_start = bar.interval_start.astimezone(NEW_YORK)
            local_end = bar.interval_end.astimezone(NEW_YORK)
            print(
                f"{local_start:%H:%M:%S}-{local_end:%H:%M:%S} ET "
                f"OHLC={bar.open:.2f}/{bar.high:.2f}/{bar.low:.2f}/{bar.close:.2f} "
                f"volume={bar.volume:.0f} trades={bar.trade_count} "
                f"bid/ask={bar.latest_bid:.2f}/{bar.latest_ask:.2f}"
            )
        opening_range = opening_builder.ranges[0]
        print()
        print("OPENING RANGE")
        print(
            f"OHLC={opening_range.range_open:.2f}/{opening_range.range_high:.2f}/"
            f"{opening_range.range_low:.2f}/{opening_range.range_close:.2f}"
        )
        print(f"Volume: {opening_range.total_volume:.0f}")
        print(f"Completed bars: {opening_range.completed_bar_count}")
        print(f"Complete: {opening_range.complete}")
        print()
        print("EVALUATION WINDOW")
        for bar in opening_builder.evaluation_bars:
            local_start = bar.interval_start.astimezone(NEW_YORK)
            print(f"{local_start:%H:%M:%S} ET completed close={bar.close:.2f}")
        latest_bar = opening_builder.evaluation_bars[-1]
        latest_quote = quotes[-1]
        print()
        print("PRICE SEMANTICS")
        print(f"Signal reference: completed-bar close {completed_bar_signal_price(latest_bar):.2f}")
        print(f"Future buy reference: latest ask {future_buy_execution_reference(latest_quote):.2f}")
        print(f"Future sell reference: latest bid {future_sell_execution_reference(latest_quote):.2f}")
        print("Bar high/low are range values, never fill prices")
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
