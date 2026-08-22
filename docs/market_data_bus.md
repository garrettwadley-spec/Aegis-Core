# Market Data Bus

F004 converts provider-neutral `RawMarketData` observations into immutable,
canonical `MarketData` domain objects and publishes `MarketDataReceived` through
the foundation Event Bus.

## Flow

1. `ReplaySource` yields boundary observations.
2. `MarketDataBus.ingest()` validates and normalizes each observation.
3. F002 Clock assigns `received_at`, event time, and event sequence.
4. F001 Event Bus synchronously publishes the exact canonical object.

Invalid symbols, sources, prices, volumes, or timestamps are rejected before
an event is created.

## Local Demo

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1.venv\Scripts\python.exe -m scripts.run_marketdata_demo
```

Live provider integration is future work. F004 contains no broker credentials,
network calls, indicators, snapshots, feature storage, or strategy logic.
