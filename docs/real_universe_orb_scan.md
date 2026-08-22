# Real Historical Universe ORB Scan

LAUNCH-009 evaluates the unchanged Opening Range Breakout strategy across the
stock-labeled portion of the local Stooq-style U.S. five-minute archive. It
streams symbols in deterministic order, routes historical bars through the
existing adapter and Market Data Bus, derives factors from canonical history,
and sends genuine signals through the existing offline paper decision and
next-observation outcome pipeline.

## Fixed Universe And Period

- Source root: `C:\Users\garre\Downloads\5_us_txt\data\5 min\us`
- Included: `nasdaq stocks`, `nyse stocks`, `nysemkt stocks`
- Excluded: `nasdaq etfs`, `nyse etfs`, `nysemkt etfs`
- Evaluation period: 2026-01-05 through 2026-04-23, inclusive
- Earlier sessions: factor lookback only
- Duplicate symbols: retain the lexicographically first source path

The directory labels provide the broadest defensible equity classification in
the archive. Stock-labeled directories may still contain exchange-listed
units, warrants, or preferreds; the scanner does not infer exclusions from
filenames or observed performance.

## Unchanged Rules

Evaluation occurs at completed ten-minute boundaries during regular New York
market hours. An observation is universe-eligible when price is from 2.50 to
8.00 inclusive and current-session cumulative volume is greater than 1,000,000.
The existing strategy then requires relative volume at least 4.0, open-to-current
price change at least 8.0 percent, RSI below 40, and a MACD upward cross below
zero. At most one paper decision may be made per symbol and session.

Independent strategy-factor counts are measured among universe-eligible points
with sufficient canonical factor history. The sequential funnel always applies
the mission-specified condition order.

## Evidence Boundary

Decision and outcome records use:

- Input origin: `REAL_HISTORICAL_UNIVERSE_REPLAY_WITH_MARKET_DERIVED_FACTORS`
- Learning eligibility: `REAL_HISTORICAL_UNIVERSE_NEXT_OBSERVATION_EVIDENCE`
- Outcome horizon: `NEXT_CANONICAL_OBSERVATION`

This is real historical next-observation strategy evidence. It is not live or
forward-test evidence and does not represent a complete position lifecycle.
Zero genuine signals produce no decision or outcome records.

## Run

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1\runs\python-3.11.9-embed\python.exe -m scripts.run_real_universe_orb_scan
```

Artifacts are written beneath `runs/real_universe_scan/<run_id>/`, which is
ignored by Git. A complete run writes the manifest, universe summary, attrition
funnel, top-20 near misses, and summary. Decision and outcome journals are
written only when genuine signals exist. `--maximum-files` is for debug runs
only and must not be used for production evidence.
