# LAUNCH-010 Capability Manifest

## Capability

Aegis can diagnose the four-gate ORB conjunction in one deterministic real-data
pass, preserve all market-derived factors, maintain isolated paper evidence for
five fixed variants, and separate development from holdout without changing the
production strategy.

## Reused Authorities

- F001/F002 provide ordered events, replay time, and process sequencing.
- F003 preserves immutable factor and market provenance.
- F004 MarketDataBus remains the canonical ingestion route.
- F005 MarketSnapshot remains the paper decision state boundary.
- LAUNCH-005/006 provide offline one-share execution and next-observation scoring.
- LAUNCH-007 owns factor definitions and production ORB thresholds.
- LAUNCH-008R owns historical bar adaptation.
- LAUNCH-009 owns the fixed universe, period, cadence, and streaming scan rules.

## Joint Evidence

The 16-pattern table totals 259,011 sufficient-history observations: 162,930
development and 96,081 holdout. The exact leave-one-out intersections are:

- Baseline 1111: 0
- No MACD 1110: 62 (43 development, 19 holdout)
- No RSI 1101: 25 (17 development, 8 holdout)
- No price change 1011: 29 (16 development, 13 holdout)
- No relative volume 0111: 0

MACD is the uniquely largest exact leave-one-out incompatibility in this fixed
universe and period. This conclusion comes from the joint pattern table, not
from sequential funnel order.

## Variant Evidence

- V0: 0 signals in both windows.
- V1: 29 development and 13 holdout signals; 42 outcomes total.
- V2: 17 development and 7 holdout signals; 24 outcomes total.
- V3: 15 development and 13 holdout signals; 28 outcomes total.
- V4: 0 signals in both windows.

V1 alone meets both predeclared sample-count labels. Its observed directional
accuracy was 62.96 percent development and 61.54 percent holdout. V2 observed
46.67 and 28.57 percent; V3 observed 42.86 and 53.85 percent. These values are
descriptive next-observation results, not statistical or profitability claims.

## Self Review

### No Production Strategy Changed

Confirmed. `OpeningRangeStrategy` was not modified. V0 invokes the existing
strategy; advisory variants are research-labeled signals in an isolated runner.

### No Threshold Changed

Confirmed. Price, volume, relative-volume, price-change, RSI, MACD definition,
indicator periods, lookback, and ten-minute cadence are unchanged.

### No Variant Was Selected After Holdout

Confirmed. V0-V4 and both date windows were immutable before the full pass.
Holdout results cannot alter variant definitions in the implementation.

### No Profitability Claim Is Justified

Confirmed. Outcomes are one-share next-observation marks without realistic
entry latency, spread, slippage, exits, holding period, capital, or position
state. Sample adequacy certifies count only.

### Exact Next Decision Supported By The Evidence

Authorize a separate, predeclared controlled validation mission for V1 MACD
advisory over a new fixed out-of-sample historical period. Keep MACD calculated
and recorded, keep all thresholds unchanged, and do not alter or promote the
production strategy unless that independent mission is reviewed and approved.

## Known Limits

- Source-provider identity remains MEDIUM confidence.
- Thirty-two selected archive files are empty and explicitly skipped.
- Stock-directory labels cannot prove common-share type for every file.
- The holdout is historical, not a live or forward test.
- No position lifecycle or statistical-significance analysis is included.
