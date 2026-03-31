print("RUNNING REAL BACKTEST FILE")
import pandas as pd



def backtest_run(strategy="sma", symbols=None, params=None):

    symbols = symbols or ["SPY"]
    params = params or {"sma_fast": 50, "sma_slow": 200}

    df = pd.read_csv("aegis/data_storage/SPY.csv")

    fast = params["sma_fast"]
    slow = params["sma_slow"]

    # RSI
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # Moving averages
    df["fast_ma"] = df["close"].rolling(fast).mean()
    df["slow_ma"] = df["close"].rolling(slow).mean()

    # Signal (Step 3)
    df["vol_avg"] = df["volume"].rolling(20).mean()
    df["signal"] = (
        (df["rsi"] < 30) &
        (df["close"] < df["slow_ma"]) &
        (df["volume"] > df["vol_avg"])
    ).astype(int)

    # ✅ STEP 4 — MUST BE HERE (inside function)
    df["position"] = df["signal"]

    df["exit"] = (
        (df["rsi"] > 50) |
        (df["close"] > df["slow_ma"])
    ).astype(int)

    df["position"] = df["position"].replace(0, pd.NA).ffill().fillna(0)
    df.loc[df["exit"] == 1, "position"] = 0

    df["returns"] = df["close"].pct_change()
    df["strategy_returns"] = df["position"].shift(1) * df["returns"]

    sharpe = df["strategy_returns"].mean() / df["strategy_returns"].std()

    return {
        "strategy": strategy,
        "symbols": symbols,
        "sharpe": float(round(sharpe, 3)),
        "maxDD": float(df["strategy_returns"].min()),
        "params": params
    }


