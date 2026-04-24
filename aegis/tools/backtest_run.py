import pandas as pd
import numpy as np

def backtest_run(strategy="macd_intraday", symbols=None, params=None):

    print("RUNNING REAL BACKTEST FILE")

    # =========================
    # LOAD DATA
    # =========================
    df = pd.read_csv("aegis/data_storage/SPY.csv")

    # Convert timestamp if needed
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

    # =========================
    # INDICATORS
    # =========================

    # MACD (custom fast version)
    fast_ema = df["close"].ewm(span=5, adjust=False).mean()
    slow_ema = df["close"].ewm(span=13, adjust=False).mean()

    df["macd"] = fast_ema - slow_ema
    df["signal_line"] = df["macd"].ewm(span=4, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["signal_line"]

    # RSI (short for intraday)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # Volume filter
    df["vol_avg"] = df["volume"].rolling(20).mean()

    # =========================
    # 🔥 KEY FIX — ENTRY LOGIC
    # =========================

    # Setup conditions (not entry yet)
    df["setup"] = (
        (df["rsi"] < 30) &                    # oversold
        (df["volume"] > df["vol_avg"])       # volume confirmation
    )

    # MACD turning upward (momentum shift)
    df["macd_turn"] = (
        (df["macd"] > df["macd"].shift(1)) &
        (df["macd_hist"] > df["macd_hist"].shift(1))
    )

    # 🔥 CONFIRMATION (THIS IS YOUR EDGE)
    df["confirmation"] = df["close"] > df["close"].shift(1)

    # FINAL SIGNAL
    df["signal"] = (df["close"] > df["close"].shift(1)).astype(int)

    # =========================
    # DEBUG
    # =========================
    print("Total signals:", df["signal"].sum())

    # =========================
    # RETURNS
    # =========================
    df["returns"] = df["close"].pct_change()
    df["strategy_returns"] = df["signal"].shift(1) * df["returns"]

    # =========================
    # PERFORMANCE
    # =========================
    std = df["strategy_returns"].std()

    if std == 0 or np.isnan(std):
        sharpe = 0
    else:
        sharpe = df["strategy_returns"].mean() / std

    return {
        "strategy": strategy,
        "symbols": symbols,
        "sharpe": float(round(sharpe, 3)),
        "maxDD": float(df["strategy_returns"].min()),
        "params": params
    }