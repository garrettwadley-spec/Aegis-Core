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

LAUNCH-011F corrects the confirmed fractional-share parser mismatch and keeps
parsing separate from consolidated bar eligibility. Present `ds` takes
precedence over `s`, exact quantity is retained with `Decimal`, and the existing
bar builder receives only three normalized update flags plus any unresolved
condition IDs. Volume-only intervals are retained without inventing OHLC.

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
the existing stream classifier.

The saved credentialed REST result was reprocessed offline through
`MassiveStockStreamAdapter`, `LiveMarketDataBus`, and
`ThirtySecondBarBuilder`. Its original SHA-256 remained
`5345463F719A40A3F538A864E51021374437760B4ABECCF60D6BB768AF39405C`.
All 9,367 records were accepted after repair, including the 4,027 records with
`size=0` and positive `decimal_size`. Exact quantity increased from 288,334 to
288,466.398509 shares. The bar path classified 1,881 trades as fully
OHLC-eligible and 7,486 as volume-only, emitted 12 bars containing the full
exact quantity, and reported no unresolved conditions, incomplete intervals,
late trades, parser rejections, or delivery failures.

## LAUNCH-011F Evidence Status

The saved historical REST sample confirms one production parser defect: all
4,027 invalid-size rejections had `size=0` and a positive `decimal_size`, while
the former validator used only `s`. The same production path now gives present
`ds` precedence, preserves it exactly, and rejects an invalid present `ds`
without silently falling back to `s`.

Massive's consolidated condition rules are implemented for all condition IDs
encountered in that sample: 2, 10, 14, 37, 41, 52, and 53. Any no takes
precedence for its OHLCV field. Unknown IDs remain explicit and conservatively
price- and volume-ineligible. Parser failures, documented eligibility limits,
unresolved conditions, incomplete intervals, and late trades remain separately
observable.

The historical parser repair is `VERIFIED`. The original 6,242 WebSocket
rejections are `NOT YET CONFIRMED`: the retained evidence is REST data mapped
to the documented WebSocket schema, not original WebSocket payloads. WebSocket
correctness is not certified.

## Self Review

### 1. What External Evidence Exists?

The classified WebSocket diagnostic recorded seven recognized control messages
and no trade payloads. Separately, the credentialed historical REST diagnostic
saved 9,367 genuine SPY, NVDA, and AAPL trades. LAUNCH-011F reprocessed those
unchanged records locally; no new request or credential was needed.

### 2. Were Real Trades Received?

Not in the latest classified WebSocket diagnostic. The earlier 6,242-message
run retained no category or payload evidence sufficient to identify valid
trades. Genuine historical REST trades exercised the production normalizer and
bar path, but cannot stand in for original WebSocket payload evidence.

### 3. Were Real Quotes Received?

No, as expected for Developer delayed mode. Twelve deterministic NBBO quote
fixtures continue to cover the retained Advanced-plan parser offline.

### 4. Were Completed 30-Second Bars Produced?

Yes. The saved historical sample produced 12 completed bars with exact combined
volume 288466.398509, while excluding 7,486 volume-only trades from OHLC. There
were no incomplete intervals or unresolved conditions in that sample. The
effect of the original 6,242 WebSocket rejections remains unconfirmed.

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

Run one bounded delayed WebSocket diagnostic during trade activity. The secure
PowerShell flow keeps the key in process memory, captures no authentication
payload, and limits the run to 300 seconds:

```powershell
& {
    $workspace = 'C:\Users\garre\Aegis-worktrees\launch-011-massive-live-stream'
    $python = 'C:\Users\garre\Aegis-worktrees\foundation-integration-v1\runs\python-3.11.9-embed\python.exe'
    Set-Location -LiteralPath $workspace -ErrorAction Stop
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $diagnostic = Join-Path $workspace "runs\massive_diagnostics\launch-011f-websocket-$stamp.json"
    $secureKey = $null
    $keyPointer = [IntPtr]::Zero
    try {
        $secureKey = Read-Host 'Enter your replacement MASSIVE_API_KEY' -AsSecureString
        $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $env:MASSIVE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
        $env:MASSIVE_DATA_MODE = 'delayed'
        $env:MASSIVE_WS_URL = 'wss://delayed.massive.com/stocks'
        & $python -m scripts.run_massive_live_smoke `
            --mode delayed `
            --symbols 'SPY,NVDA,AAPL' `
            --duration-seconds 300 `
            --diagnostic-path $diagnostic
        Write-Host "Python exit code: $LASTEXITCODE"
    }
    finally {
        Remove-Item Env:MASSIVE_API_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:MASSIVE_DATA_MODE -ErrorAction SilentlyContinue
        Remove-Item Env:MASSIVE_WS_URL -ErrorAction SilentlyContinue
        if ($keyPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
        }
        if ($null -ne $secureKey) {
            $secureKey.Dispose()
        }
    }
}
```

The run must receive actual `T` messages before it can validate WebSocket field
semantics or compare rejection categories with the historical finding. Delayed
bars support pipeline and strategy engineering, not live execution references.
Before real-time shadow operation, upgrade to Massive Stocks Advanced and prove
genuine trade and NBBO quote traffic with zero unresolved conditions, delivery
failures, incomplete price coverage, and late-trade exclusions.

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
