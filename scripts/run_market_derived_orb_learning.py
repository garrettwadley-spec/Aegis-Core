"""Run the first market-derived ORB decision and outcome loop offline."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from aegis.clock import ClockMode, system_clock
from aegis.execution import DecisionJournal, PaperDecisionService
from aegis.marketdata import (
    SYNTHETIC_FACTOR_ORIGIN,
    CanonicalMarketHistory,
    MarketDataBus,
    OpeningRangeCalculationConfig,
    OpeningRangeFactorCalculator,
    RawMarketData,
    ReplaySource,
)
from aegis.outcomes import (
    EVALUATION_HORIZON,
    OutcomeJournal,
    OutcomeObserver,
    format_feedback_summary,
    summarize_outcomes,
)
from aegis.snapshot import MarketSnapshotBuilder
from aegis.strategies import OpeningRangeStrategy, SnapshotStrategyBridge


SYMBOL = "AEGIS-DEMO"
PRIOR_DATES = (
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 1, 9),
    date(2026, 1, 12),
    date(2026, 1, 13),
    date(2026, 1, 14),
    date(2026, 1, 15),
    date(2026, 1, 16),
)


def session_time(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def observation(last: float, volume: float, timestamp: datetime) -> RawMarketData:
    return RawMarketData(
        symbol=SYMBOL,
        exchange="XNAS",
        bid=last - 0.02,
        ask=last + 0.02,
        last=last,
        volume=volume,
        source="synthetic-replay",
        source_timestamp=timestamp,
    )


def current_session_prices() -> tuple[float, ...]:
    peak = 140.6286067155259
    trough = 106.46743994392972
    final = 108.01143630133951
    rising = tuple(100.0 + (peak - 100.0) * index / 4 for index in range(5))
    declining = tuple(
        peak + (trough - peak) * index / 47
        for index in range(1, 48)
    )
    rebound = tuple(
        trough + (final - trough) * index / 3
        for index in range(1, 4)
    )
    return rising + declining + rebound


def replay_observations() -> tuple[RawMarketData, ...]:
    observations: list[RawMarketData] = []
    for day in PRIOR_DATES:
        observations.extend(
            (
                observation(100.0, 100.0, session_time(day, 14, 30)),
                observation(100.0, 300.0, session_time(day, 14, 40)),
            )
        )

    prices = current_session_prices()
    start = session_time(date(2026, 1, 20), 14, 30)
    observations.extend(
        observation(
            price,
            100.0 + (1_000.0 * index / (len(prices) - 1)),
            start + timedelta(seconds=index * 10),
        )
        for index, price in enumerate(prices)
    )
    return tuple(observations)


def main() -> None:
    system_clock.set_mode(
        ClockMode.REPLAY,
        replay_start_time="2026-01-05T14:30:00+00:00",
        replay_step_seconds=1.0,
        sequence_start=1,
    )
    try:
        market_data_bus = MarketDataBus()
        history = CanonicalMarketHistory()
        snapshot_builder = MarketSnapshotBuilder()
        market_data_bus.subscribe(history)
        market_data_bus.subscribe(snapshot_builder)
        list(ReplaySource(replay_observations()).run(market_data_bus))
        snapshot = snapshot_builder.build()

        factors = OpeningRangeFactorCalculator(
            history,
            OpeningRangeCalculationConfig(),
        ).calculate(SYMBOL, input_origin=SYNTHETIC_FACTOR_ORIGIN)
        bridge = SnapshotStrategyBridge(
            OpeningRangeStrategy(),
            opening_range_factors={SYMBOL: factors},
        )
        signal = bridge.evaluate(snapshot)[0]

        print("MARKET-DERIVED ORB FACTORS")
        print(f"Symbol: {factors.symbol}")
        print(f"Session Open: {factors.session_open_price:.4f}")
        print(f"Current Price: {factors.current_price:.4f}")
        print(f"Relative Volume: {factors.relative_volume:.4f}")
        print(f"Price Change %: {factors.price_change_pct:+.4f}%")
        print(f"RSI: {factors.rsi:.4f}")
        print(f"MACD: {factors.macd:.6f}")
        print(f"MACD Signal: {factors.macd_signal:.6f}")
        print(
            "MACD Cross Up Below Zero: "
            f"{'YES' if factors.macd_cross_up_below_zero else 'NO'}"
        )
        print(f"Source Observations: {len(factors.source_event_sequences)}")
        print(f"Prior Sessions Used: {len(factors.prior_sessions_used)}")

        decision_journal = DecisionJournal()
        decision = PaperDecisionService(decision_journal).execute(
            signal,
            snapshot,
            opening_range_factors=factors,
        )
        response = decision.execution_result.broker_response
        print("\nAUTONOMOUS PAPER DECISION")
        print(f"Strategy: {decision.request.strategy}")
        print(f"Action: {decision.request.side.value}")
        print(f"Quantity: {decision.request.quantity}")
        print(f"Entry: {response['fill_price']:.4f}")
        print(f"Paper Order ID: {response['paper_order_id']}")

        outcome_journal = OutcomeJournal()
        observer = OutcomeObserver(outcome_journal)
        observer.observe_decision(decision)
        market_data_bus.subscribe(observer)
        later = market_data_bus.ingest(
            observation(
                factors.current_price + 1.0,
                1_200.0,
                session_time(date(2026, 1, 20), 14, 39),
            )
        )
        outcome = (
            observer.outcomes[-1]
            if observer.outcomes
            else outcome_journal.outcome_for(
                decision.record["decision_record_id"],
                EVALUATION_HORIZON,
            )
        )
        return_text = (
            f"+${outcome.signed_return:.2f}"
            if outcome.signed_return >= 0
            else f"-${abs(outcome.signed_return):.2f}"
        )
        direction = (
            "FLAT"
            if outcome.directional_correct is None
            else "YES" if outcome.directional_correct else "NO"
        )
        print("\nOUTCOME")
        print(f"Later Mark: {later.last:.4f}")
        print(f"Signed Return: {return_text}")
        print(f"Return %: {outcome.signed_return_pct:+.4%}")
        print(f"Directional Correct: {direction}")
        print(f"Learning Eligibility: {outcome.learning_eligibility}")
        print(f"Decision Journal: {decision_journal.path.as_posix()}")
        print(f"Outcome Journal: {outcome_journal.path.as_posix()}")

        print("\nFEEDBACK SUMMARY")
        print(format_feedback_summary(summarize_outcomes(outcome_journal.path)))
    finally:
        system_clock.set_mode(ClockMode.LIVE)


if __name__ == "__main__":
    main()
