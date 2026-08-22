# ORB Gate Ablation

LAUNCH-010 is a bounded research-only review of the unchanged Opening Range
Breakout conjunction. It reuses LAUNCH-009's stock-directory universe, fixed
2026-01-05 through 2026-04-23 period, historical adapter, Market Data Bus,
canonical history, and market-derived factor calculator. Each sufficient-history
point is classified once, then evaluated against five predeclared gate masks.

## Predeclared Windows

- Development: 2026-01-05 through 2026-03-13 inclusive
- Holdout: 2026-03-16 through 2026-04-23 inclusive
- Earlier sessions: factor lookback only

The source aggregate remains
`44809429EFAF6CC9BF9FDD4C09D93553CBD01A2DD0462F38AE65E39CB489C215`.
No symbol, date, threshold, indicator period, or variant changes after either
window is observed.

## Fixed Variants

- V0 baseline requires relative volume, price change, RSI, and MACD.
- V1 makes MACD advisory; the other three conditions remain required.
- V2 makes RSI advisory; the other three conditions remain required.
- V3 makes price change advisory; the other three conditions remain required.
- V4 makes relative volume advisory; the other three conditions remain required.

Production `OpeningRangeStrategy` remains unchanged. The thresholds remain
relative volume >= 4.0, price change >= 8.0 percent, RSI < 40, and MACD upward
cross below zero. Universe eligibility remains price 2.50-8.00 inclusive and
cumulative session volume > 1,000,000 at completed ten-minute boundaries.

## Measured Diagnosis

Across 259,011 universe-eligible sufficient-history points, baseline pattern
1111 occurred zero times. Exact leave-one-out patterns were: no MACD 62, no RSI
25, no price change 29, and no relative volume zero. After the one-signal per
symbol/session/variant limit, V1 produced 42 signals, V2 produced 24, and V3
produced 28. V0 and V4 produced none.

V1 produced 29 development and 13 holdout signals, meeting the mission's sample
count threshold in both windows. Observed next-observation directional accuracy
was 62.96 percent in development and 61.54 percent in holdout. These descriptive
results do not establish statistical significance, profitability, execution
quality, or position-lifecycle performance.

## Evidence Boundary

Every research decision is one-share PAPER execution and is scored against
`NEXT_CANONICAL_OBSERVATION`. Records use:

- Input origin: `REAL_HISTORICAL_UNIVERSE_REPLAY_WITH_MARKET_DERIVED_FACTORS`
- Eligibility: `RESEARCH_ABLATION_NEXT_OBSERVATION_EVIDENCE`

This is not production strategy evidence, live evidence, forward-test evidence,
or complete position-lifecycle evidence. No variant is promoted automatically.

## Run

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1\runs\python-3.11.9-embed\python.exe -m scripts.run_orb_gate_ablation
```

Artifacts are written beneath `runs/orb_gate_ablation/<run_id>/`, which is
ignored by Git. `--maximum-files` is debug-only and must not be used for a full
evidence run.
