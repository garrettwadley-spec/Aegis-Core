# Live 30-Second Market Data

## Scope

LAUNCH-010 adds a market-data-only Alpaca WebSocket adapter and a deterministic
provider-neutral path from live trades and quotes to completed 30-second bars,
the 09:30-09:35 ET opening range, and completed bars exposed during the
09:35-10:00 ET evaluation window. It does not read account state, place orders,
or run a strategy.

## Stream Modes

| Mode | Endpoint | Symbols | Coverage |
| --- | --- | --- | --- |
| `TEST` | `wss://stream.data.alpaca.markets/v2/test` | `FAKEPACA` | `TEST_FEED` |
| `LIVE_IEX` | `wss://stream.data.alpaca.markets/v2/iex` | explicit list, maximum 20 | `IEX_ONLY` |
| `LIVE_SIP` | `wss://stream.data.alpaca.markets/v2/sip` | explicit list, maximum 20 | `CONSOLIDATED_SIP` |

The adapter authenticates, subscribes to trades and quotes, normalizes provider
messages to immutable `LiveTrade` or `LiveQuote` values, and only then delivers
them to `LiveMarketDataBus`. Retries and the smoke-test runtime are bounded.

## Credentials

Configure these names in the local environment:

```text
ALPACA_API_KEY
ALPACA_API_SECRET
ALPACA_DATA_FEED
```

Use `test`, `iex`, or `sip` for `ALPACA_DATA_FEED` as appropriate. Values must
not be committed, logged, or pasted into engineering reports. `.env.example`
contains names and a non-secret feed example only.

## Bar Semantics

- Intervals are fixed UTC-aligned half-open windows: `[start, end)`.
- Source timestamps assign eligible trades to intervals.
- Open is the first eligible trade price received for the interval.
- High and low are the maximum and minimum eligible trade prices.
- Close is the final eligible trade price received for the interval.
- Volume is the sum of eligible trade sizes.
- Quotes never contribute to OHLCV. The latest source-time quote known at close
  is attached separately as `latest_bid` and `latest_ask`.
- A bar is emitted only after a source-time watermark reaches its interval end.
- No-trade intervals produce no bar.
- A trade for an already closed interval is explicitly rejected and recorded;
  completed bars are never reopened or rewritten.
- Source trade IDs and F001 event sequences remain on the completed bar.

The signal reference is the latest fully completed bar close. A future buy must
reference the current ask or the next eligible post-signal trade; a future sell
must reference the current bid or the next eligible post-signal trade. Bar high
and low may define ranges or risk boundaries but are never fill prices.

## Opening Range

`OpeningRangeBuilder` consumes `ThirtySecondBarClosed` events. It accepts only
bars fully inside 09:30:00-09:35:00 ET, materializes immutable
`OpeningRangeState`, and publishes `OpeningRangeCompleted`. `complete` is true
only when all ten UTC-aligned 30-second intervals are present. Missing trade
intervals remain visible as incomplete coverage rather than fabricated candles.

Completed bars whose starts fall from 09:35:00 inclusive to 10:00:00 exclusive
are exposed through `evaluation_bars` for the next strategy contract.

## Commands

```powershell
.venv\Scripts\python.exe -m scripts.run_30s_bar_demo
.venv\Scripts\python.exe -m scripts.run_alpaca_test_stream
```

The offline demo requires no network or credentials. The Alpaca test-stream
script runs for at most 90 seconds and reports
`BLOCKED_BY_MISSING_CREDENTIALS` when the three local variables are absent.

## Feed Limits

IEX is an exchange-specific view and is classified `IEX_ONLY`; it is not a
consolidated representation of U.S. trading. SIP requires account entitlement
and is classified `CONSOLIDATED_SIP`. Subscription status records requested,
accepted, and rejected symbols so partial coverage cannot be mistaken for full
watchlist coverage.
