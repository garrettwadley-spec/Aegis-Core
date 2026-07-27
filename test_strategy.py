from aegis.strategies import OpeningRangeStrategy

strategy = OpeningRangeStrategy()

market = {
    "symbol": "SPY",
    "relative_volume": 5,
    "price_change_pct": 10,
    "rsi": 32,
    "macd_cross": True,
}

signal = strategy.evaluate(market)

print(signal)