# F004 Capability Manifest

## Capability

F004 provides provider-neutral market-data validation, canonicalization,
synchronous publication, deterministic local replay, and a visible launch demo.

## Public Surface

- `RawMarketData`
- `MarketData`
- `MarketDataBus.ingest(raw_market_data) -> MarketData`
- `MarketDataBus.subscribe(subscriber) -> Subscription`
- `ReplaySource.run(market_data_bus)`
- `MarketDataReceived`

## Implementation Decisions

- Validation occurs before event creation, so invalid input emits no event.
- Canonical observations are immutable F003 `DomainObject` instances.
- F002 Clock owns Aegis-generated timestamps and sequencing.
- F001 Event Bus owns publication and deterministic dispatch.
- Replay uses a fixed in-memory tuple and the production ingestion path.

## Self Review

### Architecture Rules Satisfied

- Provider input is separated from canonical domain truth.
- Clock and Event Bus foundation ownership is preserved.
- Event payload is the exact immutable canonical object.
- No provider, broker, strategy, indicator, snapshot, or feature-store logic was added.

### Deviations

None.

### Risks

- Float values retain normal floating-point representation limits.
- Publication is process-local and synchronous by design for the launch MVP.

### Future Improvements

- Add live provider adapters behind the existing `RawMarketData` boundary.
- Add Market Snapshot only as a separately approved capability.
- Add persistence and observability only when launch usage proves the need.
