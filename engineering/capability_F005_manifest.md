# F005 Capability Manifest

## Capability

F005 materializes the latest canonical observation per symbol as one immutable,
deterministically ordered market snapshot with source event provenance.

## Public Surface

- `MarketSnapshot`
- `MarketSnapshotBuilder.receive(event)`
- `MarketSnapshotBuilder.build() -> MarketSnapshot`
- `MarketSnapshotBuilder.subscribe(subscriber) -> Subscription`
- `MarketSnapshotCreated`

## Implementation Decisions

- The builder is subscribed directly to F004 `MarketDataReceived` events.
- Highest event sequence wins for each symbol, including out-of-order delivery.
- Current observations are ordered by ascending source event sequence.
- Snapshot time and all event sequences remain owned by F002 Clock.
- Publication uses the existing synchronous F001 EventBus.

## Self Review

### Architecture Rules Satisfied

- Snapshot state contains only canonical immutable F004 `MarketData` objects.
- Provenance maps one-to-one to snapshot records.
- F001, F002, and F003 ownership boundaries are preserved.
- The replay demo traverses the production ingestion and snapshot path.

### Known Deviations

None.

### Known Risks

- State is process-local and in-memory for the launch MVP.
- Snapshot creation is explicit rather than scheduled.

### Future Improvements

- **FUTURE WORK:** Add richer fields such as breadth, sector state, macro
  context, volatility, regimes, and indicators only through separately
  approved capabilities.
- Add persistence, scheduling, and live provider connections when required by
  the operating paper-learning loop.
