import json
from aegis.capabilities.brokers.etrade.broker import ETradeBroker

broker = ETradeBroker()

for name, result in {
    "accounts": broker.accounts(),
    "quote": broker.quote("SPY"),
    "positions": broker.positions(),
    "balances": broker.balances(),
    "orders": broker.orders(),
     "preview_order": broker.preview_equity_order("SPY", 1, "BUY"),
}.items():
    print(f"\n=== {name.upper()} ===")
    print("Status:", result["status_code"])

    if result["json"] is not None:
        print(json.dumps(result["json"], indent=2)[:2000])
    else:
        print(result["raw_preview"])