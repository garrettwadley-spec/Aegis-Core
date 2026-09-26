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

Focused historical-diagnostic evidence proves the documented REST-to-WebSocket
field mapping, exact fixed sample window, pagination and record caps, truncation
reporting, unchanged raw-record retention, credential exclusion, and reuse of
the existing stream classifier. This is offline test evidence only until a
credentialed historical request is run.

## LAUNCH-011E External Evidence Status

An operator-run delayed-feed test reported 6,242 messages through the former
undifferentiated malformed counter. No rejected payload samples or category
counts were retained. A subsequent classified delayed-feed run authenticated
and subscribed successfully, but received only seven recognized control
messages: zero trades, zero malformed messages, and zero delivery failures. Its
primary counts reconciled exactly. That quiet-window result does not explain the
earlier 6,242 messages.

`MASSIVE_API_KEY` was absent from the current Codex process, so the fixed
historical REST diagnostic was not run against Massive and no parser correction
was made.

Root cause is `UNCONFIRMED`. It is also `UNCONFIRMED` whether rejected messages
contained valid trades and whether their exclusion changed bar OHLC or volume.
The bounded diagnostic report is now required to answer both questions.

## Self Review

### 1. Was The LAUNCH-011E External Diagnostic Run?

Yes, the classified WebSocket diagnostic was run by the operator. It recorded
seven recognized control messages and no trade payloads, so it supplied no
rejection sample capable of explaining the legacy count. The historical REST
diagnostic remains blocked by the absent key in the current Codex process.

### 2. Were Real Trades Received?

Not in the latest classified WebSocket diagnostic. The earlier 6,242-message
run retained no category or payload evidence sufficient to identify valid
trades. The only accepted trades reproduced in the current work remain
deterministic fixture trades.

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

Configure `MASSIVE_API_KEY` locally and run the fixed historical REST diagnostic
with the masked-key PowerShell flow. The script queries SPY, NVDA, and AAPL for
September 25, 2026, 14:00-14:02 America/New_York, with a maximum of 10,000
records per symbol:

```powershell
& {
    $workspace = 'C:\Users\garre\Aegis-worktrees\launch-011-massive-live-stream'
    $python = 'C:\Users\garre\Aegis-worktrees\foundation-integration-v1\runs\python-3.11.9-embed\python.exe'
    Set-Location -LiteralPath $workspace -ErrorAction Stop
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $diagnostic = Join-Path $workspace "runs\massive_diagnostics\historical-rest-$stamp.json"
    $secureKey = $null
    $keyPointer = [IntPtr]::Zero
    try {
        $secureKey = Read-Host 'Enter your replacement MASSIVE_API_KEY' -AsSecureString
        $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $env:MASSIVE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
        & $python -m scripts.run_massive_historical_trade_diagnostic --output $diagnostic
        Write-Host "Python exit code: $LASTEXITCODE"
    }
    finally {
        Remove-Item Env:MASSIVE_API_KEY -ErrorAction SilentlyContinue
        if ($keyPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
        }
        if ($null -ne $secureKey) {
            $secureKey.Dispose()
        }
    }
}
```

Review raw records, category counts, and bounded sanitized samples before
changing the parser. Historical REST evidence can confirm domain-validation
behavior but cannot certify the WebSocket transport schema or resolve the
legacy 6,242-message issue by itself. A bounded WebSocket run that receives
trade payloads remains required. Delayed trades and completed bars can support
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
