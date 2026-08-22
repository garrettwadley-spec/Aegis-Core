# Market Snapshot

F005 turns the canonical `MarketDataReceived` stream into an immutable current
market state. `MarketSnapshotBuilder` retains the highest-sequence observation
for each symbol, orders current observations by source event sequence, and
publishes the exact resulting `MarketSnapshot` as `MarketSnapshotCreated`.

## Production Path

1. `ReplaySource` feeds `RawMarketData` into `MarketDataBus`.
2. F004 emits canonical `MarketDataReceived` events.
3. A subscribed `MarketSnapshotBuilder` updates latest-per-symbol state.
4. `build()` timestamps the snapshot with F002 Clock and publishes it through F001.

Building before any market data has arrived raises `ValueError`.

## Local Demo

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1.venv\Scripts\python.exe -m scripts.run_snapshot_demo
```

Indicators, breadth, sectors, macro data, volatility, regimes, persistence,
and live providers are future work, not launch requirements for F005.
