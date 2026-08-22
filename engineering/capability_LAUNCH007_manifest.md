# LAUNCH-007 Capability Manifest

## Capability

Aegis can derive all Opening Range strategy inputs from bounded canonical market
history, execute a synthetic replay paper decision, and score its later outcome.

## Reused Authorities

- F001 EventBus sequence orders canonical history.
- F002 owns all Aegis timestamps.
- F003 DomainObject owns immutable factor identity and provenance.
- MarketSnapshot remains current-state authority.
- Existing strategy, paper execution, decision, and outcome pipelines are reused.

## Deterministic Definitions

- Price change: current price relative to the first regular-session price.
- RSI: Wilder smoothing, default period 14.
- MACD: SMA-seeded EMA 12 minus EMA 26, with EMA 9 signal.
- Relative volume: current cumulative-volume delta divided by the mean same
  ten-minute bucket delta from 10 prior completed New York sessions.

## Self Review

### Factor-Calculation Correctness

Deterministic references cover Wilder RSI, EMA/MACD, below-zero upward crossover,
session open, cumulative-volume buckets, prior-session selection, failure modes,
immutability, and provenance.

### Synthetic Replay Evidence

The `AEGIS-DEMO` path proves that computed factors can generate an actionable
signal and durable paper outcome. Its price and volume history is deliberately
synthetic and labeled `SYNTHETIC_CANONICAL_REPLAY_WITH_MARKET_DERIVED_FACTORS`.

### Real Historical-Market Evidence

None. LAUNCH-007 does not ingest a real historical provider dataset, so its
records cannot support historical profitability claims.

### Live-Market Evidence

None. No live feed or broker is used, and no record is labeled as live evidence.

### What Aegis May Learn

Aegis may treat the records as canonical replay strategy evidence for pipeline,
factor, decision, execution, and scoring correctness.

### What Aegis May Not Learn

Aegis may not infer strategy profitability, statistical significance, market
generalization, or live execution performance from these synthetic records.

## Known Limits

- The bounded history is in-memory and process-local.
- JSONL exactly-once protection remains process-local for concurrent writers.
- The next canonical observation remains an MVP outcome horizon.

## Next Evidence Step

Replay a pinned real historical market dataset through `MarketDataBus` using the
same timestamp, cumulative-volume, factor, decision, and outcome contracts.
