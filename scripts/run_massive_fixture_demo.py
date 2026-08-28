"""Run deterministic Massive-shaped messages through the existing live path."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import EventBus
from aegis.marketdata import (
    LiveMarketDataBus,
    LiveQuote,
    LiveTrade,
    MassiveStockStreamAdapter,
    OpeningRangeBuilder,
    ThirtySecondBar,
    ThirtySecondBarBuilder,
)


def _milliseconds(timestamp: datetime) -> int:
    return int(timestamp.timestamp() * 1000)


def main() -> None:
    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2026-01-02T14:40:00+00:00",
        replay_step_seconds=0.001,
        sequence_start=1,
    )
    try:
        event_bus = EventBus()
        live_bus = LiveMarketDataBus(event_bus)
        bar_builder = ThirtySecondBarBuilder(event_bus)
        opening_builder = OpeningRangeBuilder(event_bus)
        observations: list[LiveTrade | LiveQuote] = []
        adapter = MassiveStockStreamAdapter(
            symbols=("SPY",),
            observation_sink=lambda item: (
                observations.append(item),
                live_bus.ingest(item),
            ),
            api_key="offline-fixture",
        )
        adapter.handle_message(
            {
                "ev": "status",
                "status": "auth_success",
                "message": "authenticated",
            }
        )
        adapter.handle_message(
            {
                "ev": "status",
                "status": "success",
                "message": "subscribed to: T.SPY,Q.SPY",
            }
        )

        start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
        provider_sequence = 1000
        for index in range(12):
            interval_start = start + timedelta(seconds=30 * index)
            base = 500.00 + 0.10 * index
            provider_sequence += 1
            adapter.handle_message(
                {
                    "ev": "Q",
                    "sym": "SPY",
                    "bp": round(base - 0.02, 2),
                    "bs": 20,
                    "bx": 11,
                    "ap": round(base + 0.02, 2),
                    "as": 25,
                    "ax": 12,
                    "c": 1,
                    "i": [2, 7],
                    "t": _milliseconds(interval_start + timedelta(seconds=1)),
                    "q": provider_sequence,
                    "z": 3,
                }
            )
            for offset, price_delta, size, suffix in (
                (5, 0.00, 100, "A"),
                (20, 0.05 if index % 2 == 0 else -0.03, 50, "B"),
            ):
                provider_sequence += 1
                adapter.handle_message(
                    {
                        "ev": "T",
                        "sym": "SPY",
                        "p": round(base + price_delta, 2),
                        "s": size,
                        "x": 4,
                        "i": f"M{index + 1:02d}{suffix}",
                        "c": [12, 37],
                        "t": _milliseconds(
                            interval_start + timedelta(seconds=offset)
                        ),
                        "pt": _milliseconds(
                            interval_start + timedelta(seconds=offset)
                        ) - 1,
                        "q": provider_sequence,
                        "z": 3,
                    }
                )

        bar_builder.advance("SPY", start + timedelta(minutes=6))
        event_bus.dispatch()
        opening_builder.advance("SPY", start + timedelta(minutes=6))
        event_bus.dispatch()

        trades = tuple(item for item in observations if isinstance(item, LiveTrade))
        quotes = tuple(item for item in observations if isinstance(item, LiveQuote))
        latest_bar = bar_builder.bars[-1]
        opening_range = opening_builder.ranges[0]
        latency = adapter.latency_statistics
        capacity = adapter.capacity_statistics

        print("MASSIVE FIXTURE")
        print(f"Authenticated: {adapter.status.authenticated}")
        print(f"Subscribed: {adapter.status.subscribed}")
        print(f"Control messages: {adapter.status.control_messages_received}")
        print(f"Trades: {len(trades)}")
        print(f"Quotes: {len(quotes)}")
        print(f"First trade provider sequence: {trades[0].metadata['provider_sequence']}")
        print(f"Trade conditions: {trades[0].conditions}")
        print(
            "Quote provenance: "
            f"condition={quotes[0].metadata['condition']} "
            f"indicators={quotes[0].metadata['indicators']} "
            f"tape={quotes[0].metadata['tape']}"
        )
        print()
        print("30-SECOND BARS")
        print(f"Completed: {len(bar_builder.bars)}")
        print(
            f"Latest: {latest_bar.symbol} close={latest_bar.close:.2f} "
            f"bid/ask={latest_bar.latest_bid:.2f}/{latest_bar.latest_ask:.2f}"
        )
        print(f"Downstream type: {type(latest_bar).__name__}")
        print()
        print("OPENING RANGE")
        print(
            f"OHLC={opening_range.range_open:.2f}/{opening_range.range_high:.2f}/"
            f"{opening_range.range_low:.2f}/{opening_range.range_close:.2f}"
        )
        print(f"Completed bars: {opening_range.completed_bar_count}")
        print(f"Complete: {opening_range.complete}")
        print(f"Downstream type: {type(opening_range).__name__}")
        print()
        print("LATENCY AND CAPACITY")
        print(f"Latency samples: {latency.count}")
        print(f"Latency min/mean/p50/p95/max ms: {latency.minimum_ms:.3f}/{latency.mean_ms:.3f}/{latency.p50_ms:.3f}/{latency.p95_ms:.3f}/{latency.maximum_ms:.3f}")
        print(f"Invalid latency samples: {latency.invalid_samples}")
        print(f"Peak messages/sec: {capacity.peak_messages_per_second}")
        print(f"Dropped: {capacity.dropped_messages}")
        print(f"Malformed: {capacity.malformed_messages}")
        self_check = all(
            isinstance(item, (LiveTrade, LiveQuote)) for item in observations
        ) and all(isinstance(bar, ThirtySecondBar) for bar in bar_builder.bars)
        print(f"Provider-neutral path: {self_check}")
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
