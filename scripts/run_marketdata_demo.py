"""Run the deterministic local Market Data Bus launch demo."""
from __future__ import annotations

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource


class DemoSubscriber(Subscriber):
    def receive(self, event: Event) -> None:
        market_data = event.payload
        print(
            f"[{event.sequence_number}] {event.event_type} "
            f"{market_data.symbol} {market_data.last:.2f} "
            f"{market_data.source} {market_data.received_at.isoformat()}"
        )


def main() -> None:
    observations = [
        RawMarketData(
            symbol="SPY",
            exchange="ARCX",
            bid=645.10,
            ask=645.14,
            last=645.12,
            volume=1_000,
            source="replay",
            source_timestamp="2026-01-02T14:29:59Z",
        ),
        RawMarketData(
            symbol="NVDA",
            exchange="XNAS",
            bid=182.42,
            ask=182.46,
            last=182.44,
            volume=800,
            source="replay",
            source_timestamp="2026-01-02T14:30:00Z",
        ),
        RawMarketData(
            symbol="AAPL",
            exchange="XNAS",
            bid=231.06,
            ask=231.10,
            last=231.08,
            volume=600,
            source="replay",
            source_timestamp="2026-01-02T14:30:01Z",
        ),
    ]

    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2026-01-02T14:30:00+00:00",
        replay_step_seconds=1.0,
        sequence_start=1,
    )
    try:
        market_data_bus = MarketDataBus()
        market_data_bus.subscribe(DemoSubscriber())
        list(ReplaySource(observations).run(market_data_bus))
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
