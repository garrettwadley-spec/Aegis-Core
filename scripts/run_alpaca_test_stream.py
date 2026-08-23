"""Run a bounded Alpaca FAKEPACA external integration smoke test."""
from __future__ import annotations

import asyncio

from aegis.eventbus import EventBus
from aegis.marketdata import (
    AlpacaStockStreamAdapter,
    AlpacaStreamMode,
    LiveMarketDataBus,
    OpeningRangeBuilder,
    ThirtySecondBarBuilder,
    credential_variables_present,
)


async def _run() -> None:
    if not credential_variables_present():
        print("Set ALPACA_API_KEY, ALPACA_API_SECRET, and ALPACA_DATA_FEED locally.")
        print("ALPACA TEST STREAM: BLOCKED_BY_MISSING_CREDENTIALS")
        return

    event_bus = EventBus()
    live_bus = LiveMarketDataBus(event_bus)
    bar_builder = ThirtySecondBarBuilder(event_bus)
    OpeningRangeBuilder(event_bus)
    adapter = AlpacaStockStreamAdapter.from_environment(
        mode=AlpacaStreamMode.TEST,
        symbols=("FAKEPACA",),
        observation_sink=live_bus.ingest,
    )
    print(f"Endpoint: {adapter.endpoint}")
    print(f"Requested symbols: {', '.join(adapter.status.requested_symbols)}")
    observations = await adapter.run(max_seconds=90)
    print(f"Authenticated: {adapter.status.authenticated}")
    print(f"Subscribed: {adapter.status.subscribed}")
    print(f"Accepted symbols: {', '.join(adapter.status.accepted_symbols) or 'None'}")
    print(f"Rejected symbols: {', '.join(adapter.status.rejected_symbols) or 'None'}")
    print(f"Normalized observations: {len(observations)}")
    print(f"Completed 30-second bars: {len(bar_builder.bars)}")
    result = "PASS" if adapter.status.authenticated and adapter.status.subscribed else "FAILED"
    print(f"ALPACA TEST STREAM: {result}")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
