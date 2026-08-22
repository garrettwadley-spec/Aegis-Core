# Real Historical OHLCV Replay

LAUNCH-008R replays a pinned local SPY.US five-minute OHLCV file through the
existing Market Data Bus, canonical history, snapshot, market-derived ORB
factors, unchanged strategy, offline paper execution, and next-observation
outcome path. The strategy never reads source rows directly and factor
calculation is pinned to the current F001 event sequence.

## Dataset And Lineage

The qualifying input is the raw per-symbol file:

`C:\Users\garre\Downloads\5_us_txt\data\5 min\us\nyse etfs\2\spy.us.txt`

Its column names and folder layout identify it as a Stooq-style local archive;
provider confidence is MEDIUM because no provider manifest accompanies the
archive. The repository transformation path is raw files to
`scripts/combine_data.py` to `data/combined_data.csv`. The replay reads the raw
SPY.US file directly, avoiding a scan of the multi-gigabyte combined file.

The source `VOL` field is per-bar volume. This is supported by the raw schema,
the combine script preserving `VOL` without accumulation, research usage, and
3,978 within-session decreases across 7,766 comparisons. The adapter preserves
each source value and derives cumulative session volume in chronological order
for the existing ORB relative-volume calculation.

## Timezone Validation

Naive source timestamps are interpreted as `Europe/Warsaw`, normalized to UTC,
then converted to `America/New_York` before session or bucket grouping. Samples
from winter, the US/Europe spring DST mismatch, and the aligned DST period map
the first source bar to 09:30 New York and the last to 15:55 New York. The local
dataset starts on 2025-11-25, so it contains no Europe/US autumn mismatch week.

## Narrow MarketData Change

`RawMarketData.bid`, `RawMarketData.ask`, `MarketData.bid`, and `MarketData.ask`
now accept `float | None`. Both values must be present or both absent. Present
quotes remain finite and non-negative, with `ask >= bid`. Historical OHLCV bars
use `bid=None`, `ask=None`, and `last=source_close`; source OHLC, per-bar volume,
derived cumulative volume, normalized timestamps, row identity, source hash,
provider identification, and code commit are retained as immutable metadata.

This is a canonical historical-representation change only. It does not declare
quote-less observations executable in a future live order path, and it does not
weaken any future live safety requirement for a complete valid bid/ask pair.

## Evidence Boundary

Decision and outcome records are labeled:

- Input origin: `REAL_HISTORICAL_LOCAL_OHLCV_REPLAY_WITH_MARKET_DERIVED_FACTORS`
- Eligibility: `REAL_HISTORICAL_REPLAY_NEXT_OBSERVATION_EVIDENCE`

The result is real historical next-observation strategy evidence. It is not a
complete position lifecycle, live evidence, forward-test evidence, or evidence
of real fill quality. A zero-signal run is a valid unchanged-strategy result.

## Run

```powershell
python -m scripts.run_real_historical_orb_replay
```

Generated journals and the run manifest are written below
`runs/historical_replay/`, which is ignored by Git.
