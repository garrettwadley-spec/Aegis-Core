print("RUNNING REAL BACKTEST FILE")

import pandas as pd


def backtest_run(strategy="macd_momentum", symbols=None, params=None):

    symbols = symbols or ["SPY"]
    params = params or {}

    df = pd.read_csv("aegis/data_storage/SPY.csv")

    # =========================
    # 🔥 MACD CORE
    # =========================
    ema_fast = df["close"].ewm(span=12).mean()
    ema_slow = df["close"].ewm(span=26).mean()

    df["macd"] = ema_fast - ema_slow
    df["signal_line"] = df["macd"].ewm(span=9).mean()

    # MACD slope = your "angle"
    df["macd_slope"] = df["macd"] - df["macd"].shift(1)

    # =========================
    # 🔥 CONDITIONS
    # =========================

    # Trend filter (simple proxy)
    df["fast_ma"] = df["close"].rolling(20).mean()
    df["slow_ma"] = df["close"].rolling(50).mean()
    trend = df["fast_ma"] > df["slow_ma"]

    # MACD crossover
    macd_cross = df["macd"] > df["signal_line"]

    # Momentum (angle)
    momentum = df["macd_slope"] > 0

    # Strong momentum (acceleration)
    strong_momentum = df["macd_slope"] > df["macd_slope"].rolling(5).mean()

    # Volume confirmation
    df["vol_avg"] = df["volume"].rolling(20).mean()
    volume_confirm = df["volume"] > df["vol_avg"] * 1.5

    # =========================
    # 🔥 SIGNAL (YOUR EDGE)
    # =========================
    df["signal"] = (
        trend &
        macd_cross &
        momentum &
        strong_momentum &
        volume_confirm
    ).astype(int)

    # =========================
    # POSITION LOGIC
    # =========================
    df["position"] = df["signal"]

    # Exit when momentum dies
    df["exit"] = (
        (df["macd"] < df["signal_line"]) |
        (df["macd_slope"] < 0)
    ).astype(int)

    df["position"] = df["position"].replace(0, pd.NA).ffill().fillna(0)
    df.loc[df["exit"] == 1, "position"] = 0

    # =========================
    # RETURNS
    # =========================
    df["returns"] = df["close"].pct_change()
    df["strategy_returns"] = df["position"].shift(1) * df["returns"]

    std = df["strategy_returns"].std()
    sharpe = df["strategy_returns"].mean() / std if std != 0 else 0

    return {
        "strategy": strategy,
        "symbols": symbols,
        "sharpe": float(round(sharpe, 3)),
        "maxDD": float(df["strategy_returns"].min()),
        "params": params
    }