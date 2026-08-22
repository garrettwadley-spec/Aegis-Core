# LAUNCH-008R Capability Manifest

## Capability

Aegis can truthfully adapt real local OHLCV bars without fabricated quotes and
replay them chronologically through its unchanged market-derived ORB decision
and next-observation outcome pipeline.

## Reused Authorities

- F001 EventBus orders every canonical observation.
- F002 Clock owns replay timestamps and process sequence generation.
- F003 DomainObject freezes canonical historical provenance.
- F004 MarketDataBus remains the only ingestion route.
- F005 MarketSnapshot remains the strategy current-state boundary.
- LAUNCH-005/006 paper decision and outcome journals remain unchanged in role.
- LAUNCH-007 owns factor definitions and ORB strategy thresholds.

## Historical Contract

- Historical bars represent missing quotes as `bid=None` and `ask=None`.
- A one-sided quote is invalid.
- Present quotes are finite, non-negative, and ordered `ask >= bid`.
- Canonical `last` is the source close.
- The first regular-session bar's immutable `source_open` drives ORB open.
- Source per-bar volume is preserved and cumulative session volume is derived.

## Determinism And Lookahead

Rows are sorted by normalized UTC timestamp and source line. Each factor call is
pinned to the just-published F001 event sequence. Strategy code receives only
canonical snapshots and factor objects. Outcomes are observed only from a later
same-symbol event. The runner permits at most one decision per symbol/session.

## Dataset Evidence

- Source: Stooq-style local archive (MEDIUM provider confidence)
- Symbol: SPY.US
- Format: five-minute raw OHLCV text
- Source timezone: Europe/Warsaw, empirically validated
- Session timezone: America/New_York
- Volume: per-bar, converted to cumulative session volume for ORB
- Source choice: preferred qualifying SPY.US file, not selected by outcome

## Self Review

### Exact Architecture Change

The sole shared-contract change is optional paired `bid`/`ask` on RawMarketData
and MarketData plus boundary validation. Historical OHLCV metadata is passed to
the already-immutable DomainObject metadata mapping. No bar registry, separate
serialization system, persistence subsystem, or strategy interface was added.

### Future Live-Quote Implication

Canonical MarketData can now contain no quote pair, so any future live execution
adapter must positively require a complete valid quote where its pricing or
safety model needs one. LAUNCH-008R's offline broker intentionally prices from
historical close; this must not be generalized to live execution.

### Evidence Classification

Records are real local historical next-observation evidence. They do not model
entry latency, spread, slippage, exits, holding periods, capital, or position
state and therefore are not complete trade-performance evidence. They are not
live or forward evidence.

## Known Limits

- Provider identity is MEDIUM confidence because the local archive has no
  accompanying provider manifest.
- The available range has winter, spring mismatch, and aligned DST sessions but
  no autumn DST mismatch week.
- Next-observation scoring is not a realistic paper-position lifecycle.

## Next Action

Add the shortest realistic paper-position lifecycle: explicit entry state,
bounded exit rules, and close-to-close outcome accounting using canonical bars.
