def data_fetch(symbols=None, range_days=5):
    symbols = symbols or ["AAPL","MSFT"]
    return {"symbols": symbols, "range_days": range_days, "rows": 390*range_days}
