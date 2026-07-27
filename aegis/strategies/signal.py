from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketSignal:
    symbol: str
    action: str
    confidence: float
    strategy: str
    quantity: int = 1

    @property
    def is_valid(self) -> bool:
        return (
            self.symbol != ""
            and self.action in ("BUY", "SELL")
            and 0.0 <= self.confidence <= 1.0
            and self.quantity > 0
        )