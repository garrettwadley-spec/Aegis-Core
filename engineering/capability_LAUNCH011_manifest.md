# LAUNCH-011 Capability Manifest

## Capability

Aegis can authenticate and subscribe to a bounded Massive U.S. equities stream,
normalize provider trades and NBBO quotes into the existing provider-neutral
live objects, meter arrival/capacity behavior, and route observations through
the existing 30-second bar and five-minute opening-range engine.

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

## Self Review

### 1. Was Real External Connectivity Proven?

No. `MASSIVE_API_KEY` was absent, so the bounded live smoke exited with
`BLOCKED_BY_MISSING_CREDENTIAL` without attempting a connection.

### 2. Were Real Trades Received?

No. Twenty-four deterministic Massive-shaped fixture trades were received and
normalized; no genuine external trade was observed.

### 3. Were Real Quotes Received?

No. Twelve deterministic Massive-shaped NBBO quote fixtures were received and
normalized; no genuine external quote was observed.

### 4. Were Completed 30-Second Bars Produced?

Yes offline: twelve completed existing bars were produced. Live external bar
production remains unproven until a credentialed bounded smoke succeeds.

### 5. What Latency Was Observed?

The fixture recorded 36 valid samples: minimum 250096.000 ms, mean 426380.833
ms, p50 419048.000 ms, p95 595004.000 ms, and maximum 599002.000 ms, with zero
invalid samples. These deliberately offset replay timestamps validate the
calculation and must not be interpreted as real provider latency.

### 6. What Are The Coverage And Subscription Limits?

Only explicit `T.SYMBOL` and `Q.SYMBOL` topics are supported, with 1-20 symbols.
Wildcards and all-market throughput are prohibited. Actual entitlements,
accepted topics, and genuine message capacity remain externally unproven.

### 7. What Is The Exact Next Step?

Configure `MASSIVE_API_KEY` in the local environment and run the bounded default
live smoke. Only after genuine trades, quotes, zero drops, and completed bars are
observed should Aegis build Opening Strategy v2 in live shadow mode.

## Excluded Work

No broad-market scanner, Opening Strategy v2, shadow decision loop, execution,
orders, feature store, machine learning, dashboard, distributed ingestion, or
direct-exchange feed was added.
