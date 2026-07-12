import pandas as pd
import glob


DATA_FILES = "data/combined_data_part_*.parquet"


def max_drawdown(returns):
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    drawdown = (equity / peak) - 1
    return drawdown.min()


def run_file(file):
    df = pd.read_parquet(file, columns=[
        "ticker", "datetime", "open", "high", "low", "close", "volume"
    ])

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["time"] = df["datetime"].dt.time
    df["date"] = df["datetime"].dt.date

    # regular session only
    df = df[
        (df["time"] >= pd.to_datetime("15:30").time()) &
        (df["time"] <= pd.to_datetime("17:00").time())
    ].copy()

    df = df.sort_values(["ticker", "datetime"])

    trades = []

    for (ticker, date), g in df.groupby(["ticker", "date"]):
        opening = g[
            (g["time"] >= pd.to_datetime("15:30").time()) &
            (g["time"] < pd.to_datetime("15:45").time())
        ]

        if len(opening) < 3:
            continue

        range_high = opening["high"].max()
        range_low = opening["low"].min()

        # approximate POC as price level of highest-volume 5-min candle
        poc_row = opening.loc[opening["volume"].idxmax()]
        poc = poc_row["close"]

        after = g[g["time"] >= pd.to_datetime("15:45").time()].copy()

        for _, row in after.iterrows():
            # long breakout
            if row["close"] > range_high:
                entry = row["close"]
                stop = poc
                risk = entry - stop

                if risk <= 0:
                    break

                target = entry + (2 * risk)
                future = after[after["datetime"] > row["datetime"]]

                result = None

                for _, f in future.iterrows():
                    if f["low"] <= stop:
                        result = -risk / entry
                        break
                    if f["high"] >= target:
                        result = (target - entry) / entry
                        break

                if result is not None:
                    trades.append(result)

                break

            # short breakout
            if row["close"] < range_low:
                entry = row["close"]
                stop = poc
                risk = stop - entry

                if risk <= 0:
                    break

                target = entry - (2 * risk)
                future = after[after["datetime"] > row["datetime"]]

                result = None

                for _, f in future.iterrows():
                    if f["high"] >= stop:
                        result = -risk / entry
                        break
                    if f["low"] <= target:
                        result = (entry - target) / entry
                        break

                if result is not None:
                    trades.append(result)

                break

    return trades


def main():
    all_trades = []

    files = sorted(glob.glob(DATA_FILES))

    for i, file in enumerate(files):
        print(f"Processing {file} ({i + 1}/{len(files)})")
        all_trades.extend(run_file(file))

    returns = pd.Series(all_trades)

    print("\n=== OPENING RANGE BACKTEST ===")
    print("Trades:", len(returns))
    print("Average return:", returns.mean())
    print("Median return:", returns.median())
    print("Win rate:", (returns > 0).mean())
    print("Std:", returns.std())
    print("Score mean/std:", returns.mean() / returns.std())
    print("Max drawdown:", max_drawdown(returns))

    print("\n=== RETURN QUANTILES ===")
    print(returns.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]))


if __name__ == "__main__":
    main()