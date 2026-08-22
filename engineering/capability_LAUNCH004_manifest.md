# LAUNCH-004 Capability Manifest

## Capability

LAUNCH-004 autonomously evaluates canonical current snapshot state through the
existing Opening Range strategy and exposes its existing `MarketSignal` result.

## Existing Components Reused

- F001 EventBus and process sequence authority
- F002 system_clock
- F003 immutable DomainObject foundation
- F004 MarketDataBus and ReplaySource
- F005 MarketSnapshotBuilder and MarketSnapshot
- `StrategyBase.evaluate(dict)`, `OpeningRangeStrategy`, and `MarketSignal`

## New Bridge Components Added

- `SnapshotStrategyBridge`, an F001 subscriber and transient input adapter
- Deterministic offline ignition demo and focused bridge tests

## Architecture Rules Satisfied

- MarketSnapshot remains the only canonical current market-state authority.
- RawMarketData never enters the strategy pipeline.
- Current snapshot values override configured values in the transient input.
- Existing strategy and signal public interfaces remain unchanged.
- No Feature Store, CKM, indicator, execution, or provider subsystem was added.

## Deviations

- Production Aegis has no standalone `StrategyEngine` class. Its existing tested
  strategy pipeline invokes `StrategyBase.evaluate(dict)` directly, so the
  bridge reuses that concrete interface instead of creating a new engine.

## Risks

- Opening Range requires four factors not present in the minimal snapshot.
  LAUNCH-004 supplies the existing test-proven factor values as explicit,
  deterministic strategy configuration; they are not inferred from market data.
- Signals are process-local and are not yet durably recorded.
- The current E*TRADE paper route attempts a broker preview before falling back
  to simulation, so it is not the offline path for the next launch mission.
- Existing `ExecutionResult` timestamps use direct system time rather than F002.

## Technical Debt

- A trustworthy launch source for the four Opening Range factors is still
  required before treating autonomous paper outcomes as market-derived learning.

## Future Improvements

- Connect `MarketSignal` to the existing paper `TradeRequest` and
  `ExecutionEngine` only in the next approved launch mission.
- Record each decision, paper execution result, and outcome for learning.

## Exact Remaining Distance to Paper Execution

Map the existing `MarketSignal` to `TradeRequest`, route it through
`ExecutionEngine` in `PAPER` mode with an offline broker implementation of the
existing `BrokerProtocol`, restore F002 ownership of the execution-result
timestamp, and durably record the decision and execution result.
