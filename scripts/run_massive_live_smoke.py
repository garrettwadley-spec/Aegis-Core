"""Run a bounded real Massive equities WebSocket smoke test."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import time
from zoneinfo import ZoneInfo

from aegis.clock import system_clock
from aegis.eventbus import EventBus
from aegis.marketdata import (
    DEFAULT_MASSIVE_SYMBOLS,
    LiveMarketDataBus,
    MassiveStockStreamAdapter,
    OpeningRangeBuilder,
    ThirtySecondBarBuilder,
    massive_credential_present,
)


NEW_YORK = ZoneInfo("America/New_York")


def _symbols(value: str) -> tuple[str, ...]:
    symbols = tuple(item.strip().upper() for item in value.split(",") if item.strip())
    if not symbols:
        raise argparse.ArgumentTypeError("--symbols requires a comma-separated list")
    return symbols


def _metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f} ms"


async def _run(symbols: tuple[str, ...], duration_seconds: float) -> None:
    if not massive_credential_present():
        print("Configure MASSIVE_API_KEY locally; MASSIVE_WS_URL is optional.")
        print("MASSIVE LIVE SMOKE: BLOCKED_BY_MISSING_CREDENTIAL")
        return

    event_bus = EventBus()
    live_bus = LiveMarketDataBus(event_bus)
    bar_builder = ThirtySecondBarBuilder(event_bus)
    opening_builder = OpeningRangeBuilder(event_bus)
    observations = []
    adapter = MassiveStockStreamAdapter.from_environment(
        symbols=symbols,
        observation_sink=lambda item: (
            observations.append(item),
            live_bus.ingest(item),
        ),
    )
    await adapter.run(max_seconds=duration_seconds)

    status = adapter.status
    latency = adapter.latency_statistics
    capacity = adapter.capacity_statistics
    observed_symbols = tuple(sorted({item.symbol for item in observations}))
    bars_by_symbol = Counter(bar.symbol for bar in bar_builder.bars)
    latest_bar = bar_builder.bars[-1] if bar_builder.bars else None
    bucket_count = len(capacity.messages_per_second)
    mean_messages_per_second = (
        0.0
        if bucket_count == 0
        else sum(count for _, count in capacity.messages_per_second) / bucket_count
    )

    print("CONNECTION")
    print(f"Endpoint: {status.endpoint}")
    print(f"Authenticated: {status.authenticated}")
    print(f"Subscribed: {status.subscribed}")
    print(f"Requested subscriptions: {','.join(status.requested_subscriptions)}")
    print(f"Accepted subscriptions: {','.join(status.accepted_subscriptions) or 'None'}")
    print(f"Rejected subscriptions: {','.join(status.rejected_subscriptions) or 'None'}")
    print()
    print("OBSERVATIONS")
    print(f"Trades: {status.trades_received}")
    print(f"Quotes: {status.quotes_received}")
    print(f"Control messages: {status.control_messages_received}")
    print(f"Malformed messages: {status.malformed_messages}")
    print(f"Symbols observed: {','.join(observed_symbols) or 'None'}")
    print(f"Messages/sec: {mean_messages_per_second:.3f}")
    print(f"Peak messages/sec: {capacity.peak_messages_per_second}")
    print(f"Handler mean: {_metric(capacity.mean_handler_processing_ms)}")
    print(f"Handler maximum: {_metric(capacity.maximum_handler_processing_ms)}")
    print(f"Queue depth: {capacity.queue_depth}")
    print(f"Dropped: {capacity.dropped_messages}")
    print()
    print("THIRTY-SECOND BARS")
    print(f"Bars completed: {len(bar_builder.bars)}")
    print(
        "Bars by symbol: "
        + (",".join(f"{symbol}={count}" for symbol, count in sorted(bars_by_symbol.items())) or "None")
    )
    print(f"Latest completed-bar close: {'N/A' if latest_bar is None else f'{latest_bar.symbol} {latest_bar.close:.4f}'}")
    print(f"Latest bid/ask: {'N/A' if latest_bar is None else f'{latest_bar.latest_bid}/{latest_bar.latest_ask}'}")
    print()
    print("LATENCY")
    print(f"Count: {latency.count}")
    print(f"Minimum: {_metric(latency.minimum_ms)}")
    print(f"Mean: {_metric(latency.mean_ms)}")
    print(f"P50: {_metric(latency.p50_ms)}")
    print(f"P95: {_metric(latency.p95_ms)}")
    print(f"Maximum: {_metric(latency.maximum_ms)}")
    print(f"Negative/invalid samples: {latency.invalid_samples}")
    print()
    print("OPENING RANGE")
    if opening_builder.ranges:
        for state in opening_builder.ranges:
            print(
                f"{state.symbol} bars={state.completed_bar_count} "
                f"complete={state.complete} high={state.range_high} low={state.range_low}"
            )
    else:
        local_now = system_clock.now().astimezone(NEW_YORK).time()
        if not time(9, 30) <= local_now < time(9, 35):
            print("Opening-range validation remains pending outside 09:30-09:35 ET.")
        else:
            partial = Counter(
                bar.symbol
                for bar in bar_builder.bars
                if time(9, 30)
                <= bar.interval_start.astimezone(NEW_YORK).time()
                < time(9, 35)
            )
            print(
                "Partial opening bars: "
                + (",".join(f"{symbol}={count}" for symbol, count in sorted(partial.items())) or "None")
            )

    if (
        status.authenticated
        and status.subscribed
        and observations
        and capacity.dropped_messages == 0
        and bar_builder.bars
    ):
        result = "PASS"
    elif status.authenticated and status.subscribed:
        result = "PARTIAL"
    else:
        result = "FAILED"
    print()
    print(f"MASSIVE LIVE SMOKE: {result}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        type=_symbols,
        default=DEFAULT_MASSIVE_SYMBOLS,
        help="Comma-separated symbols, maximum 20",
    )
    parser.add_argument("--duration-seconds", type=float, default=180.0)
    args = parser.parse_args()
    asyncio.run(_run(args.symbols, args.duration_seconds))


if __name__ == "__main__":
    main()
