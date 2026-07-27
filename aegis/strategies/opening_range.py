from __future__ import annotations

from aegis.strategies.signal import MarketSignal
from aegis.strategies.strategy_base import StrategyBase


class OpeningRangeStrategy(StrategyBase):

    name = "Opening Range Breakout"

    def evaluate(self, market_data: dict) -> MarketSignal | None:

        if (
            market_data["relative_volume"] >= 4
            and market_data["price_change_pct"] >= 8
            and market_data["rsi"] < 40
            and market_data["macd_cross"]
        ):

            return MarketSignal(
                symbol=market_data["symbol"],
                action="BUY",
                confidence=.92,
                strategy=self.name,
                quantity=1,
            )

        return None