import json

from aegis.capabilities.brokers.etrade.broker import ETradeBroker
from aegis.execution import (
    ExecutionEngine,
    ExecutionMode,
    OrderRouter,
    OrderSide,
    TradeRequest,
)


broker = ETradeBroker()
router = OrderRouter(broker)

engine = ExecutionEngine(
    router=router,
    minimum_confidence=0.70,
    maximum_quantity=100,
)

request = TradeRequest(
    symbol="SPY",
    quantity=1,
    side=OrderSide.BUY,
    strategy="execution_pipeline_test",
    confidence=0.90,
    mode=ExecutionMode.PAPER,
)

result = engine.execute(request)

print(json.dumps(result.to_dict(), indent=2))