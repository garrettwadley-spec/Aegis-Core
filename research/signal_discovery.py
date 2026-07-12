import pandas as pd


FEATURE_FILE = "data/features_data.parquet"


def main():
    print("Loading feature data...")

    df = pd.read_parquet(
        FEATURE_FILE,
        columns=[
            "return_1",
            "volatility_5",
            "volume_spike",
            "trend",
            "future_return",
        ],
    )

    print("Building regimes...")

    df["volatility_regime"] = (
        df["volatility_5"] > df["volatility_5"].rolling(100).mean()
    )

    df["volume_regime"] = df["volume_spike"] > 2
    df["positive_trend"] = df["trend"] > 0
    df["negative_or_weak_trend"] = df["trend"] <= 0

    print("\n=== BUCKET RESULTS ===")

    results = df.groupby(
        [
            "volatility_regime",
            "volume_regime",
            "positive_trend",
        ]
    )["future_return"].agg(["mean", "std", "count"])

    results["score"] = results["mean"] / results["std"]
    results = results.sort_values("score", ascending=False)

    print(results)

    print("\n=== TOP CANDIDATE ===")
    print(results.head(1))


if __name__ == "__main__":
    main()