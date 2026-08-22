"""Run Aegis's first complete decision-to-outcome feedback loop."""
from __future__ import annotations

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, Subscriber
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import MarketDataBus, RawMarketData, ReplaySource
from aegis.outcomes import (
    EVALUATION_HORIZON,
    OutcomeJournal,
    OutcomeObserver,
    format_feedback_summary,
    summarize_outcomes,
)
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


class MarketDataPrinter(Subscriber):
    def receive(self, event: Event) -> None:
        market_data = event.payload
        print(
            f"[{event.sequence_number}] {event.event_type} "
            f"{market_data.symbol} last={market_data.last:.2f}"
        )


def observation(symbol: str, last: float, timestamp: str) -> RawMarketData:
    return RawMarketData(
        symbol=symbol,
        exchange="XNAS" if symbol != "SPY" else "ARCX",
        bid=last - 0.02,
        ask=last + 0.02,
        last=last,
        volume=1_000,
        source="replay",
        source_timestamp=timestamp,
    )


def main() -> None:
    strategy_bridge = SnapshotStrategyBridge(
        OpeningRangeStrategy(),
        {
            "SPY": {
                "relative_volume": 5.0,
                "price_change_pct": 10.0,
                "rsi": 32.0,
                "macd_cross": True,
            }
        },
    )
    initial_observations = [
        observation("SPY", 645.12, "2026-01-02T14:30:00Z"),
        observation("NVDA", 182.44, "2026-01-02T14:30:01Z"),
        observation("AAPL", 231.08, "2026-01-02T14:30:02Z"),
        observation("SPY", 645.36, "2026-01-02T14:30:03Z"),
    ]

    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2026-01-02T14:30:00+00:00",
        replay_step_seconds=1.0,
        sequence_start=1,
    )
    try:
        market_data_bus = MarketDataBus()
        snapshot_builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(MarketDataPrinter())
        market_data_bus.subscribe(snapshot_builder)
        snapshot_builder.subscribe(strategy_bridge)
        list(ReplaySource(initial_observations).run(market_data_bus))
        snapshot = snapshot_builder.build()

        decision = PaperDecisionService(DecisionJournal()).execute(
            strategy_bridge.last_signals[0],
            snapshot,
        )
        response = decision.execution_result.broker_response
        print("\nFIRST AUTONOMOUS PAPER DECISION")
        print(f"Strategy: {decision.request.strategy}")
        print(f"Symbol: {decision.request.symbol}")
        print(f"Action: {decision.request.side.value}")
        print(f"Quantity: {decision.request.quantity}")
        print(f"Entry Price: {response['fill_price']:.2f}")
        print(f"Paper Order ID: {response['paper_order_id']}")

        outcome_journal = OutcomeJournal()
        observer = OutcomeObserver(outcome_journal)
        observer.observe_decision(decision)
        market_data_bus.subscribe(observer)
        later = market_data_bus.ingest(
            observation("SPY", 646.36, "2026-01-02T14:31:00Z")
        )
        outcome = (
            observer.outcomes[-1]
            if observer.outcomes
            else outcome_journal.outcome_for(
                decision.record["decision_record_id"],
                EVALUATION_HORIZON,
            )
        )

        print("\nLATER MARKET OBSERVATION")
        print(f"Symbol: {later.symbol}")
        print(f"Mark Price: {later.last:.2f}")
        print(f"Source Event Sequence: {outcome.source_event_sequence}")

        print("\nFIRST AEGIS OUTCOME")
        print(f"Decision Record ID: {outcome.decision_record_id}")
        print(f"Outcome Record ID: {outcome.outcome_record_id}")
        print(f"Entry: {outcome.entry_price:.2f}")
        print(f"Mark: {outcome.mark_price:.2f}")
        return_text = (
            f"+${outcome.signed_return:.2f}"
            if outcome.signed_return >= 0
            else f"-${abs(outcome.signed_return):.2f}"
        )
        print(f"Signed Paper Return: {return_text}")
        print(f"Signed Return %: {outcome.signed_return_pct:+.4%}")
        direction = "FLAT" if outcome.directional_correct is None else (
            "YES" if outcome.directional_correct else "NO"
        )
        print(f"Directional Correct: {direction}")
        print(f"Evaluation Horizon: {outcome.evaluation_horizon}")
        print(f"Learning Eligibility: {outcome.learning_eligibility}")
        print(f"Outcome Recorded: {outcome_journal.path.as_posix()}")

        print("\nFEEDBACK SUMMARY")
        print(format_feedback_summary(summarize_outcomes(outcome_journal.path)))
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
