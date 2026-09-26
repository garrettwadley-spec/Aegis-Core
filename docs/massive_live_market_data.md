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
seconds, and an external diagnostic run is capped at five minutes. The default smoke uses SPY,
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

The official [Massive trade schema](https://www.massive.com/docs/websocket/stocks/trades)
documents integer size `s` and fractional-share size `ds`. If `ds` is present,
Aegis parses it as the effective quantity with `Decimal`; otherwise it uses
legacy `s`. A present but malformed, non-finite, zero, or negative `ds` is
rejected without falling back to `s`. The two fields are alternate
representations of one quantity and are never added together.

The original `s`, original `ds`, selected field, and exact decimal quantity are
retained in immutable `LiveTrade` metadata. `LiveTrade.size` remains a float at
the existing public compatibility boundary. The 30-second bar accumulator uses
the exact `Decimal` quantity and converts to the existing float `bar.volume`
only when it closes the bar; `exact_volume_decimal` remains in immutable bar
metadata for exact reconciliation.

### Trade Eligibility

Parsing and bar eligibility are separate. A valid trade always retains all
reported conditions. At normalization, Aegis applies the consolidated update
rules for every condition encountered in the saved LAUNCH-011F sample:

| Condition | Name | High/low | Open/close | Volume |
| --- | --- | --- | --- | --- |
| 2 | Average Price Trade | No | No | Yes |
| 10 | Derivatively Priced | Yes | No | Yes |
| 14 | Intermarket Sweep | Yes | Yes | Yes |
| 37 | Odd Lot Trade | No | No | Yes |
| 41 | Trade Thru Exempt | Yes | Yes | Yes |
| 52 | Contingent Trade | No | No | Yes |
| 53 | Qualified Contingent Trade | No | No | Yes |

Massive's documented combination rule applies independently to each aggregate
field: if any condition says no, no takes precedence. Unknown conditions remain
explicit in `unresolved_conditions` and conservatively update no OHLCV field;
they are not parser failures and are reported separately.

Condition 37 therefore contributes its exact quantity to volume without
setting open, high, low, or close. An interval containing volume-eligible
trades but no complete price coverage is retained as an
`IncompleteBarInterval`; it does not emit an invented candle. Eligibility
exclusions, incomplete intervals, late-trade rejections, and parser failures
remain separate diagnostics. These rules follow Massive's
[fractional-share guidance](https://massive.com/knowledge-base/article/how-does-massive-handle-fractional-share-trades),
[trade eligibility guidance](https://www.massive.com/blog/understanding-trade-eligibility),
and documented [conditions endpoint](https://massive.com/docs/rest/stocks/market-operations/condition-codes).

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

### Message Classification Diagnostics

Every decoded message receives exactly one primary classification:

- accepted trade or quote
- recognized control message
- intentionally ignored documented non-`T`/`Q` event
- unknown event type
- invalid JSON or payload structure
- missing or invalid symbol, timestamp, price, or size
- other domain-validation failure

Delivery failures are counted separately because a valid normalized observation
can be accepted by the parser but fail to reach the live bus. Primary counts
must sum exactly to `messages_received`.

The smoke writes a bounded JSON report to
`runs/massive_diagnostics/latest.json`. The `runs/` tree is Git-ignored. The
report retains no more than five examples per reason and only whitelists safe
market-data fields. Authentication actions, keys, headers, and raw invalid JSON
are never retained.

Documented `A`, `AM`, `LULD`, `NOI`, and `FMV` events are intentionally ignored
because the current bars are built from accepted `T` events. Their exclusion
does not directly change trade-derived OHLC or volume. Rejected `T` events can
affect both; unknown or structurally invalid payload impact remains unconfirmed
until its sanitized sample is reviewed.

An earlier operator-run delayed smoke reported 6,242 messages under the legacy
aggregate `malformed_messages` counter. That version retained no category counts
or samples, so the root cause and bar completeness are `UNCONFIRMED`. The new
report is the required evidence before any parser correction or strategy-bar
completeness claim.

The subsequent classified delayed run authenticated and subscribed successfully
but received only seven recognized control messages. It received zero trades,
zero malformed messages, and zero delivery failures. The counts reconciled, but
that quiet-window result contains no evidence about the original 6,242 rejected
messages.

### Historical REST Schema Diagnostic

`scripts.run_massive_historical_trade_diagnostic` queries the documented
[`GET /v3/trades/{stockTicker}` endpoint](https://massive.com/docs/rest/stocks/trades-quotes/trades)
for this fixed sample:

- SPY, NVDA, and AAPL
- September 25, 2026
- 14:00 inclusive through 14:02 exclusive in `America/New_York`
- at most 10,000 records per symbol

The request uses a Bearer authorization header as documented in the
[REST quickstart](https://massive.com/docs/rest/quickstart). Credentials,
authorization headers, request URLs, and pagination URLs are never written to
the artifact. Pagination links are restricted to the expected HTTPS host/path,
credential parameters are removed, and any remaining records are reported as
truncated when the per-symbol limit is reached.

Every returned REST trade object is preserved unchanged under the Git-ignored
`runs/massive_diagnostics/` tree. A separate copy is mapped into the documented
[WebSocket stock-trade schema](https://www.massive.com/docs/websocket/stocks/trades)
and passed through the existing `MassiveStockStreamAdapter` classifier:

| REST field | WebSocket field | Mapping |
| --- | --- | --- |
| `price` | `p` | unchanged |
| `size` | `s` | unchanged, including zero or missing |
| `decimal_size` | `ds` | unchanged, including fractional strings |
| `conditions` | `c` | unchanged |
| `exchange`, `id`, `sequence_number`, `tape` | `x`, `i`, `q`, `z` | unchanged |
| `sip_timestamp` | `t` | Unix nanoseconds converted to milliseconds |
| `participant_timestamp`, `trf_timestamp` | `pt`, `trft` | Unix nanoseconds converted to milliseconds |
| request ticker | `sym` | fixed endpoint ticker |
| fixed event type | `ev` | `T` |

REST-only fields such as `correction` remain in the raw record and are not
invented into the WebSocket message. Missing, zero, fractional, and rejected
market values are deliberately retained. Results are labeled
`HISTORICAL_REST_SCHEMA_DIAGNOSTIC`: they can reproduce domain/parser behavior,
but they are not original WebSocket payloads and cannot certify WebSocket
correctness.

### LAUNCH-011F Saved-Sample Reprocessing

The original Git-ignored report was reprocessed without a network request:

```text
runs/massive_diagnostics/historical-rest-20260926-030554.json
SHA-256: 5345463F719A40A3F538A864E51021374437760B4ABECCF60D6BB768AF39405C
```

Its 9,367 unchanged raw records produced this before/after evidence through the
production adapter, live bus, and bar builder:

| Measure | Before | After |
| --- | ---: | ---: |
| Accepted trades | 5,340 | 9,367 |
| Invalid-size rejections | 4,027 | 0 |
| Exact accepted quantity | 288,334 | 288,466.398509 |

All 4,027 recovered records had `size=0` and positive `decimal_size`; their
exact quantity was 125.217355 shares. Another 7.181154 fractional shares were
previously omitted from records whose rounded-down integer `size` was nonzero,
for a total legacy-size undercount of 132.398509 shares. This is a quantity
delta, not a rejected-record percentage.

The repaired path classified 1,881 trades as fully OHLC-eligible and 7,486 as
volume-only, produced 12 bars, preserved all 288,466.398509 shares in exact bar
volume, and reported zero unresolved conditions, incomplete intervals,
late-trade rejections, parser rejections, or delivery failures. The fixture's
former condition-37 price trades were corrected to price-eligible conditions;
the odd-lot regression proves an extreme odd-lot price cannot alter OHLC.

The separate before/after artifact is:

```text
runs/massive_diagnostics/historical-rest-20260926-030554-before-after.json
SHA-256: F56B4D2D0081ED5BD39F00BD1BB0EBB56E2E1B40B4214C3B2C10AFCF2077FAEF
```

This verifies the historical parser repair. It does not identify the original
6,242 WebSocket rejections or certify WebSocket correctness; a bounded run that
receives actual `T` payloads is still required.

## Delayed Trade Bar Contract

Delayed Developer data is valid for ingestion, bar-pipeline, opening-range, and
strategy engineering. Condition eligibility independently controls open/close,
high/low, and volume contribution. With no quote entitlement, `latest_bid` and
`latest_ask` remain `None`; the system neither fabricates quotes nor creates flat
candles for intervals without trades. The completed-bar close remains a signal
reference, but delayed data is classified `DELAYED_MARKET_DATA` and
`NOT_ELIGIBLE_FOR_LIVE_EXECUTION_REFERENCE`.

## Commands

```powershell
.venv\Scripts\python.exe -m scripts.run_massive_fixture_demo
.venv\Scripts\python.exe -m scripts.run_massive_live_smoke --mode delayed
.venv\Scripts\python.exe -m scripts.run_massive_live_smoke --mode delayed --duration-seconds 300 --diagnostic-path runs/massive_diagnostics/launch-011e.json
.venv\Scripts\python.exe -m scripts.run_massive_historical_trade_diagnostic
.venv\Scripts\python.exe -m scripts.run_massive_historical_trade_diagnostic --input-report runs/massive_diagnostics/historical-rest-20260926-030554.json --output runs/massive_diagnostics/historical-rest-20260926-030554-before-after.json
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
