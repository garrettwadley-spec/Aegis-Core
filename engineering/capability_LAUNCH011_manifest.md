# LAUNCH-011 Capability Manifest

## Capability

Aegis can authenticate and subscribe to a bounded Massive U.S. equities stream,
normalize provider trades and NBBO quotes into the existing provider-neutral
live objects, meter arrival/capacity behavior, and route observations through
the existing 30-second bar and five-minute opening-range engine.

LAUNCH-011D adds two explicit contracts. `DELAYED_TRADES` is the default for the
current Massive Stocks Developer plan and uses delayed `T.SYMBOL` topics only.
`REALTIME_TRADES_QUOTES` preserves the existing Advanced-plan `T.SYMBOL` and
`Q.SYMBOL` contract unchanged.

LAUNCH-011E makes stream rejection accounting explainable. Every event receives
one primary classification, primary counts reconcile exactly to messages
received, delivery failures remain separate, and at most five sanitized samples
per rejection reason can be written under the Git-ignored `runs/` tree.

## Reused Authorities

- F001 EventBus remains the only event sequence and dispatch path.
- F002 system clock owns Aegis timestamps and handler timing.
- F003 DomainObject supplies immutable identity and provenance.
- LAUNCH-010 owns `LiveTrade`, `LiveQuote`, `LiveMarketDataBus`,
  `ThirtySecondBarBuilder`, and `OpeningRangeBuilder`.
- The Alpaca adapter is retained unchanged as an inactive fallback/test path.

No Massive-specific bar, range, bus, sequence authority, or downstream market
object was created.

## Offline Evidence

The deterministic fixture processed two control messages, 24 Massive-shaped
trades, and 12 Massive-shaped quotes. It produced 12 existing
`ThirtySecondBar` objects and one complete ten-bar `OpeningRangeState`, with
latest bid/ask attached and provider sequence/condition/tape provenance intact.
Dropped and malformed counts were zero.

Fixture latency values are deterministic pipeline evidence only. They are not
claims about Massive or internet performance.

Focused delayed-mode evidence additionally proves that existing 30-second bars
build from trades alone, leave latest bid/ask unavailable, and do not fabricate
quotes or no-trade candles.

Focused diagnostic evidence proves deterministic classification, exact count
reconciliation, bounded samples, safe-field allowlisting, and separate delivery
failure accounting. These are offline instrumentation results, not evidence of
an external Massive feed.

## LAUNCH-011E External Evidence Status

An operator-run delayed-feed test reported 6,242 messages through the former
undifferentiated malformed counter. No rejected payload samples or category
counts were retained. The API key was absent during LAUNCH-011E implementation,
so the external diagnostic was not rerun and no parser correction was made.

Root cause is `UNCONFIRMED`. It is also `UNCONFIRMED` whether rejected messages
contained valid trades and whether their exclusion changed bar OHLC or volume.
The bounded diagnostic report is now required to answer both questions.

## Self Review

### 1. Was The LAUNCH-011E External Diagnostic Run?

No. `MASSIVE_API_KEY` was absent in the running process. Earlier operator output
cannot substitute for the new category counts and sanitized samples.

### 2. Were Real Trades Received?

Not during LAUNCH-011E. The earlier operator run reported genuine delayed-feed
activity, but its raw category evidence was not retained. The only evidence
reproduced in this mission was 24 deterministic fixture trades.

### 3. Were Real Quotes Received?

No, as expected for Developer delayed mode. Twelve deterministic NBBO quote
fixtures continue to cover the retained Advanced-plan parser offline.

### 4. Were Completed 30-Second Bars Produced?

Yes offline: twelve completed existing bars were produced. The operator reported
external bars, but whether the 6,242 exclusions changed their OHLC or volume is
unconfirmed until the credentialed diagnostic captures rejection categories.

### 5. What Latency Was Observed?

The fixture recorded 36 valid samples: minimum 250096.000 ms, mean 426380.833
ms, p50 419048.000 ms, p95 595004.000 ms, and maximum 599002.000 ms, with zero
invalid samples. These deliberately offset replay timestamps validate the
calculation and must not be interpreted as real provider latency.

### 6. What Are The Coverage And Subscription Limits?

Only explicit topics are supported, with 1-20 symbols. Developer delayed mode
requests `T.SYMBOL` only and is classified `FULL_MARKET_DELAYED_TRADES` and
`DELAYED_MARKET_DATA`. Advanced real-time mode requests both `T.SYMBOL` and
`Q.SYMBOL` and is classified `REALTIME_TRADES_AND_NBBO_QUOTES`. Wildcards and
all-market throughput are prohibited. Accepted-topic and capacity evidence from
the earlier external run was not retained in a diagnostic artifact.

### 7. What Is The Exact Next Step?

Configure `MASSIVE_API_KEY` locally and run the 300-second delayed diagnostic:

```powershell
Set-Location 'C:\Users\garre\Aegis-worktrees\launch-011-massive-live-stream'
& 'C:\Users\garre\Aegis-worktrees\foundation-integration-v1\runs\python-3.11.9-embed\python.exe' -m scripts.run_massive_live_smoke --mode delayed --duration-seconds 300 --diagnostic-path runs/massive_diagnostics/launch-011e.json
```

Review category counts and sanitized samples before changing the parser or
declaring strategy bars complete. Delayed trades and completed bars can support
pipeline and strategy engineering, but not live execution references. Before
real-time shadow operation, upgrade to Massive
Stocks Advanced, set `MASSIVE_DATA_MODE=realtime`, and prove authentication,
trade and quote subscriptions, genuine trades and NBBO quotes, zero drops, zero
malformed messages, and completed 30-second bars.

## Developer And Advanced Gate

- Developer: 15-minute-delayed trades over WebSocket, no quote entitlement.
- Delayed evidence: valid for pipeline and strategy engineering.
- Delayed execution eligibility: `NOT_ELIGIBLE_FOR_LIVE_EXECUTION_REFERENCE`.
- Advanced required: real-time trades, NBBO quotes, real-time shadow decisions,
  and any live execution-reference validation.

## Excluded Work

No broad-market scanner, Opening Strategy v2, shadow decision loop, execution,
orders, feature store, machine learning, dashboard, distributed ingestion, or
direct-exchange feed was added.
