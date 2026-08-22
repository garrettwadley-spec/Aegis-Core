# LAUNCH-005 Capability Manifest

## Capability

LAUNCH-005 completes Aegis's first autonomous offline action cycle from replayed
market observations through a durable paper-decision record.

## Existing Components Reused

- MarketDataBus, ReplaySource, MarketSnapshotBuilder, and SnapshotStrategyBridge
- OpeningRangeStrategy and MarketSignal
- TradeRequest, ExecutionEngine, OrderRouter, BrokerProtocol, and ExecutionResult
- F002 system_clock for execution and journal timestamps

## New Minimal Components

- OfflinePaperBroker with deterministic canonical-price fills and order IDs
- SignalToTradeBridge with one-share PAPER requests
- LaunchSafetyGate for mode, action, symbol, quantity, and price checks
- PaperDecisionService and append-only JSON Lines DecisionJournal

## Self Review

### Genuinely Market-Derived

- Symbol, exchange, bid, ask, last, volume, provider timestamp, received time,
  canonical object identifiers, and source event sequence provenance come from
  the F004/F005 replay-to-snapshot path.
- Paper fill price is the newest canonical snapshot `last` for the signal symbol.

### Deterministic Or Configured

- Replay observations, one-share quantity, paper fill semantics, and order IDs
  are deterministic launch behavior.
- Relative volume, price-change percentage, RSI, and MACD-cross values are the
  configured factors already used by LAUNCH-004, not market-derived features.
- Every record states
  `DETERMINISTIC_REPLAY_WITH_CONFIGURED_STRATEGY_FACTORS` as `input_origin`.

### Architecture Rules Satisfied

- Existing execution interfaces are reused; no second execution engine exists.
- LIVE mode is rejected and no broker credentials or network calls are used.
- F002 owns Aegis-generated execution timestamps.
- Paper order IDs are content-derived and do not create another event sequence.
- Safety failures stop broker execution and are durably recorded as rejected.

### Deviations

None.

### Risks

- The paper fill model has no commissions, slippage, liquidity, or portfolio state.
- JSONL append is process-local and does not coordinate concurrent writers.

### Why This Is Not Strategy-Performance Evidence

The strategy factors are configured fixtures and the prices are deterministic
replay inputs. A filled paper decision proves pipeline operation, not that the
strategy predicts real market outcomes.

### Shortest Remaining Path to Genuine Outcome Learning

Observe a later canonical market price for the recorded symbol, join it to the
decision by identifiers and provenance, calculate the signed paper return, and
append an immutable outcome record that preserves the same input-origin truth.

### Future Capabilities

- Outcome observation and scoring
- Trustworthy market-derived strategy factors
- Commissions, slippage, portfolio sizing, and broader risk policy
- Live brokerage only under separately approved production authorization
