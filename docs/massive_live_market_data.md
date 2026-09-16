# Massive Live Market Data

## Scope

LAUNCH-011 makes Massive the primary live-capable U.S. equities market-data
adapter for Aegis. LAUNCH-011D adds an explicit Developer-plan mode for
15-minute-delayed trades while retaining the Advanced-plan real-time trade and
NBBO quote contract. Both modes use the unchanged provider-neutral
`LiveMarketDataBus`, `ThirtySecondBarBuilder`, and `OpeningRangeBuilder`. The
Alpaca adapter remains available as an inactive fallback/test integration.

This capability does not subscribe to all-market topics, run strategy logic,
read brokerage state, or place orders.

## Connection

The supported operating modes are:

| Mode | Endpoint | Topics | Coverage | Execution reference |
| --- | --- | --- | --- | --- |
| `DELAYED_TRADES` | `wss://delayed.massive.com/stocks` | `T.SYMBOL` only | `FULL_MARKET_DELAYED_TRADES` | Not eligible |
| `REALTIME_TRADES_QUOTES` | `wss://socket.massive.com/stocks` | `T.SYMBOL` and `Q.SYMBOL` | `REALTIME_TRADES_AND_NBBO_QUOTES` | Eligible by data contract |

The default is `DELAYED_TRADES` until the account is upgraded and real-time mode
is explicitly selected. The adapter sends the required authentication action
and then one comma-separated subscription action. A delayed subscription is:

```text
T.SPY,T.QQQ,T.NVDA
```

The retained real-time subscription for the Advanced plan is:

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
MASSIVE_DATA_MODE
MASSIVE_WS_URL
```

`MASSIVE_DATA_MODE` accepts `delayed` or `realtime` and defaults to `delayed`.
`MASSIVE_WS_URL` is optional; each mode otherwise selects its canonical endpoint.

The key is used only for the outbound authentication message. It is excluded
from status, representations, exceptions, logs, documentation, and output.
Never commit it or paste it into chat.

## Normalization

Massive `T` events become the existing immutable `LiveTrade` type. `sym`, `p`,
`s`, `x`, `i`, and `c` map to provider-neutral fields. SIP timestamp `t` becomes
`source_timestamp`; provider sequence `q`, participant timestamp `pt`, tape `z`,
and conditions are retained as immutable metadata.

In real-time mode, Massive `Q` events become the existing immutable `LiveQuote`
type. Bid/ask prices, sizes, and exchange IDs map directly. Provider sequence,
tape, condition, and indicators remain immutable metadata. Developer delayed
mode intentionally requests no quote topics and treats zero quotes as valid.

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

## Delayed Trade Bar Contract

Delayed Developer data is valid for ingestion, bar-pipeline, opening-range, and
strategy engineering. Eligible trades still define open, high, low, close,
volume, and trade count. With no quote entitlement, `latest_bid` and
`latest_ask` remain `None`; the system neither fabricates quotes nor creates flat
candles for intervals without trades. The completed-bar close remains a signal
reference, but delayed data is classified `DELAYED_MARKET_DATA` and
`NOT_ELIGIBLE_FOR_LIVE_EXECUTION_REFERENCE`.

## Commands

```powershell
.venv\Scripts\python.exe -m scripts.run_massive_fixture_demo
.venv\Scripts\python.exe -m scripts.run_massive_live_smoke --mode delayed
.venv\Scripts\python.exe -m scripts.run_massive_live_smoke --mode realtime --symbols SPY,QQQ,NVDA --duration-seconds 180
```

The fixture requires no key or network. Without `MASSIVE_API_KEY`, the live
command exits cleanly with `BLOCKED_BY_MISSING_CREDENTIAL`.

## Coverage Limitations

The Developer plan supports full-market delayed trades but no quotes. It is not
suitable for real-time shadow operation or live execution-reference validation.
Massive Stocks Advanced is required before selecting real-time mode and before
Aegis may validate current bid/ask execution references. This mission does not
prove all-market throughput, entitlement for every symbol, broad discovery,
opening-strategy behavior, or execution. Accepted and rejected topics remain
visible in immutable status so partial subscription coverage cannot be mistaken
for complete coverage.
