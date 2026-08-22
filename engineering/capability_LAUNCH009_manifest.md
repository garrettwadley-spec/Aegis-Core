# LAUNCH-009 Capability Manifest

## Capability

Aegis can scan its broad, objectively defined local U.S. historical equity
universe without loading the multi-gigabyte archive into memory, evaluate the
unchanged ORB rules through canonical market history, preserve source and factor
provenance, report complete attrition, and truthfully emit no paper activity
when no genuine signal exists.

## Reused Authorities

- F001 EventBus provides deterministic event sequence ordering.
- F002 Clock owns replay time and process sequence generation.
- F003 DomainObject provides immutable identity and provenance.
- F004 MarketDataBus remains the canonical ingestion route.
- F005 MarketSnapshot remains the strategy current-state boundary.
- LAUNCH-005/006 own paper decision, execution, and outcome records.
- LAUNCH-007 owns factor definitions and ORB strategy thresholds.
- LAUNCH-008R owns Stooq-style historical-bar adaptation.

## Production Evidence Run

- Fixed period: 2026-01-05 through 2026-04-23
- Included files: 8,533 from stock-labeled directories
- Processed symbols: 8,501
- Skipped files: 32 empty sources
- Sessions: 586,781
- Completed ten-minute evaluation points: 14,240,389
- Sufficient-history points: 259,011
- Genuine signals, paper decisions, and outcomes: 0
- Source aggregate SHA-256:
  `44809429EFAF6CC9BF9FDD4C09D93553CBD01A2DD0462F38AE65E39CB489C215`

The sequential funnel was 14,240,389 valid observations, 2,287,207 in the price
range, 386,332 above cumulative volume, 259,011 with sufficient factor history,
9,250 above relative-volume threshold, 3,231 above price-change threshold, 62
below the RSI threshold, and zero with the required MACD crossover.

## Self Review

### 1. Was The Universe Appropriate For The Strategy?

Yes. The scan used every file in the archive's NASDAQ, NYSE, and NYSE MKT
stock-labeled directories and excluded only explicitly ETF-labeled directories.
This objectively covers the intended low-priced, liquid U.S. equity profile.
Directory classification cannot distinguish every unit, warrant, or preferred,
so that ambiguity is disclosed instead of guessed away.

### 2. Were Thresholds Unchanged?

Yes. The existing `OpeningRangeStrategy` retained relative volume >= 4.0, price
change >= 8.0 percent, RSI < 40, and MACD upward cross below zero. Universe
gates remained price 2.50-8.00 inclusive and cumulative volume > 1,000,000.

### 3. Was Any Symbol Or Date Selected After Viewing Outcomes?

No. Source-directory rules and the 2026-01-05 through 2026-04-23 period were
fixed before the complete scan. Files were processed deterministically and no
result-based inclusion, exclusion, or date movement occurred.

### 4. Which Condition Eliminated The Most Candidates?

The price-range universe gate removed the most observations in absolute terms,
leaving 2,287,207 of 14,240,389. Within the unchanged strategy, relative volume
was the largest reduction, leaving 9,250 of 259,011 sufficient-history points.
At the final conjunction, RSI left 62 candidates and MACD crossover eliminated
all 62.

### 5. Did Real Historical Signals Occur?

No. No evaluation point satisfied the complete unchanged strategy, so Aegis
correctly created zero paper decisions and zero outcomes.

### 6. What Evidence Classification Is Justified?

`REAL_HISTORICAL_UNIVERSE_NEXT_OBSERVATION_EVIDENCE` is justified. The run is
real historical evidence about rule frequency and pipeline behavior. It is not
live evidence, forward evidence, or complete position-lifecycle evidence, and
it supplies no strategy return evidence because no genuine signals occurred.

### 7. What Is The Shortest Next Move Based On The Actual Funnel?

Perform a bounded, predeclared strategy-specification review focused on the
relative-volume, RSI, and MACD conjunction, using the retained near misses and
independent counts. Do not tune automatically. If the approved strategy remains
unchanged, extend to a broader fixed historical period to determine whether the
zero-signal result is period-specific before building position lifecycle work.

## Known Limits

- Provider identity remains MEDIUM confidence because the archive has no
  accompanying provider manifest.
- Thirty-two selected files were empty and are explicitly recorded as skipped.
- Stock-directory labels cannot prove common-share security type for every file.
- Next-observation scoring is not a realistic paper-position lifecycle.
