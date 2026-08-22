# Snapshot Strategy Bridge

LAUNCH-004 connects immutable `MarketSnapshotCreated` events to Aegis's existing
`StrategyBase.evaluate(dict)` interface. `SnapshotStrategyBridge` maps each
configured current snapshot record into a transient strategy input dictionary
and preserves the existing `MarketSignal` result.

## Selected Strategy

`OpeningRangeStrategy` is the existing production strategy with the shortest
offline path. Its current interface expects `symbol`, `relative_volume`,
`price_change_pct`, `rsi`, and `macd_cross`. The bridge takes canonical symbol
and market fields from `MarketSnapshot`; the four established strategy factors
remain explicit strategy configuration inputs.

## Local Demo

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1.venv\Scripts\python.exe -m scripts.run_strategy_ignition_demo
```

The bridge does not consume `RawMarketData`, calculate indicators, execute
orders, contact a broker, or create another market-state authority.
