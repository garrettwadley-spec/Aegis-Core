import pandas as pd
import os

DATA_FOLDER = r"C:\Users\garre\Downloads\5_us_txt\data\5 min\us"
OUTPUT_FILE = "combined_data.csv"

dfs = []

for root, _, files in os.walk(DATA_FOLDER):
    for file in files:
        if file.endswith(".txt"):
            path = os.path.join(root, file)

            try:
                df = pd.read_csv(path)

                # clean column names
                df.columns = [c.replace("<", "").replace(">", "").lower() for c in df.columns]

                # build datetime
                df["datetime"] = pd.to_datetime(
                    df["date"].astype(str) + df["time"].astype(str).str.zfill(6),
                    format="%Y%m%d%H%M%S"
                )

                # fix ticker (use actual data, not filename)
                df["ticker"] = df["ticker"].str.replace(".US", "", regex=False)

                # select columns
                df = df[["ticker", "datetime", "open", "high", "low", "close", "vol"]]
                df.rename(columns={"vol": "volume"}, inplace=True)

                dfs.append(df)

            except Exception as e:
                print("Skipping:", file, e)

combined = pd.concat(dfs)
combined = combined.sort_values(["ticker", "datetime"])

combined.to_csv(OUTPUT_FILE, index=False)

print("DONE")
print("Rows:", len(combined))
print("Tickers:", combined["ticker"].nunique())