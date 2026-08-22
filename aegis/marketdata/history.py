"""Bounded canonical market history ordered by F001 event sequence."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from aegis.eventbus import Event, Subscriber

from .bus import MARKET_DATA_RECEIVED
from .models import MarketData


@dataclass(frozen=True)
class MarketHistoryObservation:
    sequence_number: int
    market_data: MarketData


class CanonicalMarketHistory(Subscriber):
    """Retain a small per-symbol window solely for factor calculation."""

    def __init__(self, max_observations_per_symbol: int = 5_000) -> None:
        if max_observations_per_symbol <= 0:
            raise ValueError("history bound must be greater than zero")
        self._maximum = max_observations_per_symbol
        self._observations: dict[str, list[MarketHistoryObservation]] = {}

    def receive(self, event: Event) -> None:
        if event.event_type != MARKET_DATA_RECEIVED:
            raise ValueError("canonical history accepts MarketDataReceived only")
        if event.sequence_number is None:
            raise ValueError("MarketDataReceived event requires a sequence number")
        if not isinstance(event.payload, MarketData):
            raise TypeError("MarketDataReceived payload must be MarketData")

        symbol = event.payload.symbol
        observations = self._observations.setdefault(symbol, [])
        sequences = [item.sequence_number for item in observations]
        index = bisect_left(sequences, event.sequence_number)
        if index < len(observations):
            existing = observations[index]
            if existing.sequence_number == event.sequence_number:
                raise ValueError(
                    f"duplicate market event sequence {event.sequence_number}"
                )
        observations.insert(
            index,
            MarketHistoryObservation(event.sequence_number, event.payload),
        )
        if len(observations) > self._maximum:
            del observations[: len(observations) - self._maximum]

    def window(
        self,
        symbol: str,
        *,
        through_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[MarketHistoryObservation, ...]:
        normalized_symbol = symbol.strip().upper()
        observations = self._observations.get(normalized_symbol, ())
        selected = [
            item
            for item in observations
            if through_sequence is None
            or item.sequence_number <= through_sequence
        ]
        if limit is not None:
            if limit <= 0:
                raise ValueError("history query limit must be greater than zero")
            selected = selected[-limit:]
        return tuple(selected)
