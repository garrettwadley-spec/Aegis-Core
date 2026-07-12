import pandas as pd


FEATURE_FILE = "data/features_data.parquet"


def max_drawdown(returns):
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    drawdown = (equity / peak) - 1
    return drawdown.min()


def main():
    print("Loading feature data...")

    df = pd.read_parquet(
        FEATURE_FILE,
        columns=[
        "close",
        "volume",
        "volatility_5",
        "volume_spike",
        "trend",
        "future_return",
        ],
    )

    print("Building signal...")

    df["volatility_regime"] = (
        df["volatility_5"] > df["volatility_5"].rolling(100).mean()
    )

    df["signal"] = (
    (df["volatility_regime"] == True)
    & (df["volume_spike"] > 10)
    & (df["volume_spike"] < 50)
    & (df["trend"] <= 0)
    & (df["close"] >= 1)
    & (df["close"] <= 50)
    & (df["volume"] >= 10000)
)

    trades = df[df["signal"]].copy()


    trade_returns = trades["future_return"]
    # trade_returns = trade_returns.clip(-0.05, 0.05)

    print("\n=== BUCKET BACKTEST ===")
    print("Trades:", len(trades))
    print("Average return:", trade_returns.mean())
    print("Median return:", trade_returns.median())
    print("Win rate:", (trade_returns > 0).mean())
    print("Std:", trade_returns.std())
    print("Score mean/std:", trade_returns.mean() / trade_returns.std())
    print("Max drawdown:", max_drawdown(trade_returns))

    print("\n=== RETURN QUANTILES ===")
    print(trade_returns.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))


if __name__ == "__main__":
    main()