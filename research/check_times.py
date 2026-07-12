import pandas as pd

df = pd.read_parquet("combined_data_part_0.parquet", columns=[
    "ticker", "datetime", "open", "high", "low", "close", "volume"
])

df["datetime"] = pd.to_datetime(df["datetime"])
df["time"] = df["datetime"].dt.time

print(df.head(20))
print("\nTime range:")
print(df["time"].min(), df["time"].max())

print("\nMost common times:")
print(df["time"].value_counts().head(30).sort_index())