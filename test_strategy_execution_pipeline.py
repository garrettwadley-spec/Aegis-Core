import json

from aegis.capabilities.brokers.etrade.broker import ETradeBroker
from aegis.execution import (
    ExecutionEngine,
    ExecutionMode,
    OrderRouter,
    OrderSide,
    TradeRequest,
)
from aegis.strategies import OpeningRangeStrategy


market_data = {
    "symbol": "SPY",
    "relative_volume": 5.0,
    "price_change_pct": 10.0,
    "rsi": 32.0,
    "macd_cross": True,
}

strategy = OpeningRangeStrategy()
signal = strategy.evaluate(market_data)

if signal is None:
    print(
        json.dumps(
            {
                "status": "no_signal",
                "message": "Strategy conditions were not met.",
            },
            indent=2,
        )
    )
    raise SystemExit(0)

side = OrderSide.BUY if signal.action == "BUY" else OrderSide.SELL

trade_request = TradeRequest(
    symbol=signal.symbol,
    quantity=signal.quantity,
    side=side,
    strategy=signal.strategy,
    confidence=signal.confidence,
    mode=ExecutionMode.PAPER,
)

broker = ETradeBroker()
router = OrderRouter(broker)

engine = ExecutionEngine(
    router=router,
    minimum_confidence=0.70,
    maximum_quantity=100,
)

result = engine.execute(trade_request)

print(
    json.dumps(
        {
            "market_data": market_data,
            "signal": {
                "symbol": signal.symbol,
                "action": signal.action,
                "confidence": signal.confidence,
                "strategy": signal.strategy,
                "quantity": signal.quantity,
            },
            "execution": result.to_dict(),
        },
        indent=2,
    )
)