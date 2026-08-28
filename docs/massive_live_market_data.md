# Massive Live Market Data

## Scope

LAUNCH-011 makes Massive the primary live-capable U.S. equities market-data
adapter for Aegis. It normalizes Massive stock trades and NBBO quotes into the
existing provider-neutral `LiveTrade` and `LiveQuote` objects, then uses the
unchanged `LiveMarketDataBus`, `ThirtySecondBarBuilder`, and
`OpeningRangeBuilder`. The Alpaca adapter remains available as an inactive
fallback/test integration.

This capability does not subscribe to all-market topics, run strategy logic,
read brokerage state, or place orders.

## Connection

The default endpoint is:

```text
wss://socket.massive.com/stocks
```

The adapter sends the required authentication action and then one comma-separated
subscription action containing explicit topics such as:

```text
T.SPY,T.QQQ,T.NVDA,Q.SPY,Q.QQQ,Q.NVDA
```

`T.*` and `Q.*` are rejected. The watchlist must contain 1-20 explicit symbols.
Connection attempts are limited to three, reconnect delay is capped at five
seconds, and a smoke run is capped at ten minutes. The default smoke uses SPY,
QQQ, NVDA, AAPL, and TSLA for 180 seconds.

## Credentials

Set the key in the local process environment and optionally override the secure
WebSocket endpoint:

```text
MASSIVE_API_KEY
MASSIVE_WS_URL
```

The key is used only for the outbound authentication message. It is excluded
from status, representations, exceptions, logs, documentation, and output.
Never commit it or paste it into chat.

## Normalization

Massive `T` events become the existing immutable `LiveTrade` type. `sym`, `p`,
`s`, `x`, `i`, and `c` map to provider-neutral fields. SIP timestamp `t` becomes
`source_timestamp`; provider sequence `q`, participant timestamp `pt`, tape `z`,
and conditions are retained as immutable metadata.

Massive `Q` events become the existing immutable `LiveQuote` type. Bid/ask
prices, sizes, and exchange IDs map directly. Provider sequence, tape,
condition, and indicators remain immutable metadata.

Malformed symbols, prices, sizes, or timestamps are rejected before the live
bus. Crossed quotes are rejected. Status and control messages update adapter
status only and never reach bar or strategy logic. Aegis `system_clock` supplies
`received_at`, `created_at`, message buckets, and handler timing.

## Observability

For every accepted trade or quote, the adapter calculates:

```text
provider_to_receive_latency_ms = received_at - Massive SIP timestamp
```

This is an observed end-to-end arrival metric affected by Massive
infrastructure, the internet path, local clock synchronization, and local
processing. It is not pure provider latency. Statistics include count, minimum,
mean, nearest-rank p50/p95, and maximum. Negative/non-finite samples are counted
as invalid rather than corrected. Malformed messages are counted separately.

Capacity snapshots expose per-second message counts, peak messages per second,
mean/maximum handler time, synchronous queue depth (`0`), dropped messages, and
malformed messages. This bounded synchronous pilot must retain a dropped count
of zero.

## Commands

```powershell
.venv\Scripts\python.exe -m scripts.run_massive_fixture_demo
.venv\Scripts\python.exe -m scripts.run_massive_live_smoke
.venv\Scripts\python.exe -m scripts.run_massive_live_smoke --symbols SPY,QQQ,NVDA --duration-seconds 180
```

The fixture requires no key or network. Without `MASSIVE_API_KEY`, the live
command exits cleanly with `BLOCKED_BY_MISSING_CREDENTIAL`.

## Coverage Limitations

This mission proves a bounded direct Massive stream contract only. It does not
prove all-market throughput, entitlement for every symbol, broad discovery,
opening-strategy behavior, or execution. Accepted and rejected topics remain
visible in immutable status so partial subscription coverage cannot be mistaken
for complete coverage.
