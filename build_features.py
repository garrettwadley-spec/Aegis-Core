import pandas as pd
import glob

INPUT_FILES = "combined_data_part_*.parquet"
OUTPUT_FILE = "features_data.parquet"

all_chunks = []

files = glob.glob(INPUT_FILES)

for i, file in enumerate(files):
    print(f"Processing {file} ({i+1}/{len(files)})")

    df = pd.read_parquet(file)

    df = df.sort_values(["ticker", "datetime"])

    # ===== CORE FEATURES =====

    # returns
    df["return_1"] = df.groupby("ticker")["close"].pct_change()

    # rolling volatility (5 bars ~ 25 min)
    df["volatility_5"] = df.groupby("ticker")["return_1"].rolling(5).std().reset_index(0, drop=True)

    # rolling volatility (20 bars ~ 100 min)
    df["volatility_20"] = df.groupby("ticker")["return_1"].rolling(20).std().reset_index(0, drop=True)

    # moving averages
    df["ma_5"] = df.groupby("ticker")["close"].rolling(5).mean().reset_index(0, drop=True)
    df["ma_20"] = df.groupby("ticker")["close"].rolling(20).mean().reset_index(0, drop=True)

    # trend signal
    df["trend"] = df["ma_5"] - df["ma_20"]

    # volume spike
    df["vol_avg_20"] = df.groupby("ticker")["volume"].rolling(20).mean().reset_index(0, drop=True)
    df["volume_spike"] = df["volume"] / df["vol_avg_20"]

    # price range (intrabar volatility)
    df["range"] = (df["high"] - df["low"]) / df["close"]

    all_chunks.append(df)

# combine everything
final = pd.concat(all_chunks)

# clean NaNs (first rows of rolling windows)
final = final.dropna()

# save
final.to_parquet(OUTPUT_FILE)

print("DONE")
print("Rows:", len(final))