"""Small deterministic local replay source."""
from __future__ import annotations

from collections.abc import Iterable, Iterator

from .bus import MarketDataBus
from .models import MarketData, RawMarketData


class ReplaySource:
    """Replay a fixed observation sequence through MarketDataBus.ingest."""

    def __init__(self, observations: Iterable[RawMarketData]) -> None:
        self._observations = tuple(observations)

    def run(self, market_data_bus: MarketDataBus) -> Iterator[MarketData]:
        for observation in self._observations:
            yield market_data_bus.ingest(observation)
