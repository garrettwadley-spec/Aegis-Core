# LAUNCH-010 Capability Manifest

## Capability

Aegis can normalize an Alpaca-compatible trade/quote stream into immutable live
observations, deterministically close trade-derived 30-second OHLCV bars, build
the first five regular-session minutes, and expose completed evaluation-window
bars without allowing provider payloads into downstream strategy code.

## Reused Authorities

- F001 EventBus owns deterministic event publication and sequence provenance.
- F002 Clock owns all Aegis-generated timestamps and process sequences.
- F003 DomainObject supplies immutable identity, trace, correlation, metadata,
  and creation provenance.
- F004 Market Data Bus conventions define the canonical normalization boundary.
- LAUNCH-009 remains historical diagnostic evidence; its five-minute scan and
  zero-signal result are not treated as a production strategy conclusion.

## New Surface

- `LiveTrade`, `LiveQuote`, `ThirtySecondBar`, and `OpeningRangeState`
- `LiveMarketDataBus`
- `ThirtySecondBarBuilder` and explicit late-trade rejection records
- `OpeningRangeBuilder`
- `AlpacaStockStreamAdapter` for TEST, LIVE_IEX, and LIVE_SIP modes
- Deterministic offline demo and bounded external test-stream smoke script

The only dependency change is an explicit `websockets==17.0.1` pin. That
version was already installed and validated in the project environment through
the existing `uvicorn[standard]` dependency; it is now direct because production
code imports it.

## Self Review

### 1. Why Five-Minute Data Was Insufficient

The intended opening strategy must observe and potentially act within the first
15-30 minutes. A five-minute bar exposes only a few coarse completed states and
the existing 12/26/9 MACD therefore describes a much longer horizon than the
opening decision. LAUNCH-009's zero signals remain valid evidence about that
specific five-minute conjunction, not evidence that a correctly specified
opening strategy is unviable.

### 2. Exact Bar-Price Semantics

OHLC and volume come only from eligible trades inside a fixed source-time
30-second UTC interval: first trade open, maximum high, minimum low, final trade
close, and summed trade size volume. Quotes are retained separately. No-trade
intervals emit nothing, and a closed bar is never reopened.

### 3. Exact Future Execution-Price Semantics

Signals reference the latest fully completed bar close. A future buy references
the current ask or next eligible post-signal trade; a future sell references the
current bid or next eligible post-signal trade. Bar high and low are never fills.

### 4. External Alpaca Connectivity

External connectivity is proven only when the bounded FAKEPACA script reports
successful authentication and subscription. Missing local credential variables
produce `BLOCKED_BY_MISSING_CREDENTIALS` without blocking offline capability.

### 5. Feed And Coverage Limitations

TEST is synthetic provider integration. IEX is classified `IEX_ONLY` and is not
consolidated market coverage. SIP is `CONSOLIDATED_SIP` but depends on account
entitlement. Live subscriptions are explicit, limited to 20 requested symbols,
and retain accepted/rejected status.

### 6. Before The First Live-Shadow Opening Decision

Define and approve a bounded Opening Strategy v2 contract that consumes only
completed 30-second bars and opening-range state, then connect it to shadow
paper decisions with no order-routing authority. External TEST authentication
should also be exercised when local Alpaca credentials are available.

## Launch Boundaries

No order execution, account access, scanner, universe discovery, RSI, MACD,
strategy tuning, position lifecycle, dashboard, machine learning, or
self-modification is included.
