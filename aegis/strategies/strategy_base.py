from __future__ import annotations

from abc import ABC, abstractmethod

from aegis.strategies.signal import MarketSignal


class StrategyBase(ABC):

    name = "Base Strategy"

    @abstractmethod
    def evaluate(self, market_data: dict) -> MarketSignal | None:
        """Return a MarketSignal or None."""
        raise NotImplementedError