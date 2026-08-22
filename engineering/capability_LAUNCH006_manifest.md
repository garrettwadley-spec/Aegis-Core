# LAUNCH-006 Capability Manifest

## Capability

LAUNCH-006 closes the first autonomous paper decision feedback loop by scoring
the first later canonical same-symbol observation and recording the outcome.

## Existing Components Reused

- DecisionJournal and RecordedPaperDecision
- MarketDataBus, MarketData, MarketSnapshot, and F001 EventBus delivery
- PaperDecisionService, ExecutionResult, and F002 system_clock

## New Minimal Components

- Immutable RecordedDecisionOutcome
- OutcomeObserver with sequence-aware first-mark selection and deduplication
- OutcomeJournal extending the existing append-only JSONL pattern
- Read-only FeedbackSummary functions

## Self Review

### What Aegis Has Actually Learned

Aegis has recorded whether one deterministic paper BUY was directionally correct
at the next canonical replay observation and its signed paper return. It has also
proven durable decision-to-outcome linkage and scoring infrastructure.

### What Aegis Has Not Learned

Aegis has not learned that OpeningRangeStrategy is profitable, that its factors
predict returns, or that the replay result generalizes to live markets.

### Canonical Market-Derived Data

Entry and mark prices, symbol, canonical MarketData identifiers, F001 sequence
provenance, and F002 timestamps flow through the replay MarketData pipeline.

### Configured Strategy Inputs

Relative volume, price-change percentage, RSI, and MACD-cross remain configured
fixtures explicitly labeled by `input_origin`.

### Why Outcomes Are Not Profitability Evidence

The factor values and price path are deterministic mission inputs. The outcome
validates pipeline mechanics and arithmetic, not market predictive power.

### Exact Capability Required Before Genuine Strategy Learning

Replace each configured Opening Range factor with a trustworthy value calculated
from canonical timestamped market observations, preserve its derivation and
provenance in the decision record, then score subsequent real paper outcomes.

### Architecture Rules Satisfied

- Decision and execution records remain unchanged and append-only.
- Outcome records are immutable, separate, traceable, and append-only.
- F001 sequence provenance selects the first eligible later observation.
- F002 owns outcome evaluation time.
- No ML, strategy mutation, weighting, optimization, or new market-state authority.

### Known Risks

- JSONL exactly-once checks are process-local and not safe for concurrent writers.
- NEXT_CANONICAL_OBSERVATION is a launch horizon, not a final performance horizon.

### Future Improvements

- Canonical market-derived Opening Range factors
- Additional explicit evaluation horizons
- Concurrent-writer-safe persistence only when operating scale requires it
