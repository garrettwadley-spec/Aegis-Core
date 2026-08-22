"""Canonical market snapshot domain model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aegis.domain import DomainObject
from aegis.marketdata import MarketData


@dataclass(frozen=True, kw_only=True)
class MarketSnapshot(DomainObject):
    """Immutable current market state with source event provenance."""

    as_of: datetime
    market_data: tuple[MarketData, ...]
    source_event_sequences: tuple[int, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "market_data", tuple(self.market_data))
        object.__setattr__(
            self,
            "source_event_sequences",
            tuple(self.source_event_sequences),
        )
        if len(self.market_data) != len(self.source_event_sequences):
            raise ValueError(
                "market_data and source_event_sequences must have equal lengths"
            )
