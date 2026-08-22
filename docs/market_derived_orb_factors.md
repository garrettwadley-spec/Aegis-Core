# Market-Derived ORB Factors

LAUNCH-007 subscribes a bounded `CanonicalMarketHistory` to the existing Market
Data Bus. `OpeningRangeFactorCalculator` pins observations by F001 sequence and
creates one immutable F003 `OpeningRangeFactors` object without OS time access or
external services.

The calculation uses the first regular-session price for percentage change,
Wilder RSI, SMA-seeded 12/26/9 EMA MACD, and cumulative-volume deltas for the
same New York ten-minute bucket across 10 prior completed sessions. Missing or
invalid history raises an explicit error; no fallback factor values are inserted.

`SnapshotStrategyBridge` accepts the derived factor object and gives its values
precedence over the legacy configuration path. Paper decision records preserve
the factor object ID, values, configuration, source IDs, source sequences, input
origin, and replay learning eligibility.

## Evidence Boundary

- Factor-calculation correctness: supported by deterministic numerical tests.
- Synthetic replay evidence: validates the complete autonomous pipeline and its
  arithmetic using deliberately constructed canonical observations.
- Real historical-market evidence: not produced by LAUNCH-007.
- Live-market evidence: not produced by LAUNCH-007.

LAUNCH-007 records can prove that Aegis derives and uses factors correctly. They
cannot establish that Opening Range Breakout is profitable or generalizes to
historical or live markets.

## Demo

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1.venv\Scripts\python.exe -m scripts.run_market_derived_orb_learning
```
