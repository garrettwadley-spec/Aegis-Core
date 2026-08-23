"""Focused LAUNCH-010 live stream and 30-second bar tests."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import Event, EventBus, Subscriber
from aegis.marketdata import (
    THIRTY_SECOND_BAR_CLOSED,
    AlpacaStockStreamAdapter,
    AlpacaStreamMode,
    LiveMarketDataBus,
    LiveQuote,
    LiveTrade,
    OpeningRangeBuilder,
    ThirtySecondBar,
    ThirtySecondBarBuilder,
    completed_bar_signal_price,
    credential_variables_present,
    future_buy_execution_reference,
    future_sell_execution_reference,
    interval_for,
    normalize_alpaca_message,
)


UTC = timezone.utc


def trade_message(
    timestamp: str = "2026-01-02T14:30:05Z",
    *,
    price: float = 10.0,
    size: float = 100,
    trade_id: str = "T1",
) -> dict[str, object]:
    return {
        "T": "t",
        "S": "spy",
        "i": trade_id,
        "x": "v",
        "p": price,
        "s": size,
        "c": ["@"],
        "t": timestamp,
    }


def quote_message(
    timestamp: str = "2026-01-02T14:30:01Z",
    *,
    bid: float = 9.98,
    ask: float = 10.02,
) -> dict[str, object]:
    return {
        "T": "q",
        "S": "spy",
        "bx": "v",
        "bp": bid,
        "bs": 20,
        "ax": "v",
        "ap": ask,
        "as": 25,
        "t": timestamp,
    }


def normalized_trade(**overrides: object) -> LiveTrade:
    message = trade_message()
    message.update(overrides)
    result = normalize_alpaca_message(message)
    assert isinstance(result, LiveTrade)
    return result


def normalized_quote(**overrides: object) -> LiveQuote:
    message = quote_message()
    message.update(overrides)
    result = normalize_alpaca_message(message)
    assert isinstance(result, LiveQuote)
    return result


def make_bar(start: datetime, *, high: float = 10.2, low: float = 9.8) -> ThirtySecondBar:
    return ThirtySecondBar(
        symbol="SPY",
        interval_start=start,
        interval_end=start + timedelta(seconds=30),
        open=10.0,
        high=high,
        low=low,
        close=10.1,
        volume=100,
        trade_count=1,
        latest_bid=10.08,
        latest_ask=10.12,
        source_trade_ids=(f"T-{start.isoformat()}",),
        source_event_sequences=(1,),
    )


class RecordingSubscriber(Subscriber):
    def __init__(self) -> None:
        self.events: list[Event] = []

    def receive(self, event: Event) -> None:
        self.events.append(event)


class LiveMarketTestCase(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-01-02T14:30:00+00:00",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def pipeline(self):
        event_bus = EventBus()
        live_bus = LiveMarketDataBus(event_bus)
        builder = ThirtySecondBarBuilder(event_bus)
        return event_bus, live_bus, builder


class TestAlpacaNormalization(LiveMarketTestCase):
    def test_trade_normalization_is_provider_neutral_and_immutable(self):
        trade = normalized_trade()
        self.assertEqual((trade.symbol, trade.exchange), ("SPY", "V"))
        self.assertEqual((trade.price, trade.size), (10.0, 100.0))
        self.assertEqual(trade.trade_id, "T1")
        self.assertEqual(trade.conditions, ("@",))
        self.assertEqual(trade.source_timestamp, datetime(2026, 1, 2, 14, 30, 5, tzinfo=UTC))
        with self.assertRaises(FrozenInstanceError):
            trade.price = 11.0  # type: ignore[misc]

    def test_quote_normalization_is_provider_neutral(self):
        quote = normalized_quote()
        self.assertEqual((quote.symbol, quote.bid_exchange, quote.ask_exchange), ("SPY", "V", "V"))
        self.assertEqual((quote.bid_price, quote.ask_price), (9.98, 10.02))
        self.assertEqual((quote.bid_size, quote.ask_size), (20.0, 25.0))

    def test_invalid_trade_price_or_size_is_rejected(self):
        for field, value in (("p", 0), ("p", float("nan")), ("s", 0), ("s", -1)):
            with self.subTest(field=field, value=value):
                message = trade_message()
                message[field] = value
                with self.assertRaises(ValueError):
                    normalize_alpaca_message(message)

    def test_invalid_or_crossed_quote_is_rejected(self):
        for bid, ask in ((10.03, 10.02), (0, 10.02), (9.98, float("inf"))):
            with self.subTest(bid=bid, ask=ask):
                with self.assertRaises(ValueError):
                    normalize_alpaca_message(quote_message(bid=bid, ask=ask))

    def test_provider_messages_cannot_bypass_normalization(self):
        delivered: list[object] = []
        adapter = AlpacaStockStreamAdapter(
            mode=AlpacaStreamMode.TEST,
            symbols=("FAKEPACA",),
            observation_sink=delivered.append,
            api_key="key",
            api_secret="secret",
        )
        observation = adapter.handle_message(trade_message())
        self.assertIs(delivered[0], observation)
        self.assertIsInstance(delivered[0], LiveTrade)
        self.assertNotIsInstance(delivered[0], dict)

    def test_credentials_are_never_rendered_or_logged(self):
        adapter = AlpacaStockStreamAdapter(
            mode=AlpacaStreamMode.TEST,
            symbols=("FAKEPACA",),
            observation_sink=lambda item: None,
            api_key="SENSITIVE_KEY",
            api_secret="SENSITIVE_SECRET",
        )
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            adapter.handle_message({"T": "success", "msg": "authenticated"})
        rendered = repr(adapter) + output.getvalue()
        self.assertNotIn("SENSITIVE_KEY", rendered)
        self.assertNotIn("SENSITIVE_SECRET", rendered)

    def test_credential_presence_requires_all_variable_names(self):
        environment = {
            "ALPACA_API_KEY": "present",
            "ALPACA_API_SECRET": "present",
            "ALPACA_DATA_FEED": "iex",
        }
        self.assertTrue(credential_variables_present(environment))
        del environment["ALPACA_API_SECRET"]
        self.assertFalse(credential_variables_present(environment))

    def test_watchlist_bound_and_coverage_are_explicit(self):
        adapter = AlpacaStockStreamAdapter(
            mode=AlpacaStreamMode.LIVE_IEX,
            symbols=("spy", "aapl"),
            observation_sink=lambda item: None,
            api_key="key",
            api_secret="secret",
        )
        adapter.handle_message({"T": "subscription", "trades": ["SPY"], "quotes": ["SPY"]})
        self.assertEqual(adapter.status.requested_symbols, ("SPY", "AAPL"))
        self.assertEqual(adapter.status.accepted_symbols, ("SPY",))
        self.assertEqual(adapter.status.rejected_symbols, ("AAPL",))
        self.assertEqual(adapter.status.coverage_classification, "IEX_ONLY")
        with self.assertRaises(ValueError):
            AlpacaStockStreamAdapter(
                mode=AlpacaStreamMode.LIVE_SIP,
                symbols=tuple(f"S{index}" for index in range(21)),
                observation_sink=lambda item: None,
                api_key="key",
                api_secret="secret",
            )

    def test_test_mode_allows_a_separate_configured_live_feed(self):
        adapter = AlpacaStockStreamAdapter.from_environment(
            mode=AlpacaStreamMode.TEST,
            symbols=("FAKEPACA",),
            observation_sink=lambda item: None,
            environment={
                "ALPACA_API_KEY": "key",
                "ALPACA_API_SECRET": "secret",
                "ALPACA_DATA_FEED": "iex",
            },
        )
        self.assertEqual(adapter.endpoint, "wss://stream.data.alpaca.markets/v2/test")


class TestThirtySecondBars(LiveMarketTestCase):
    def test_interval_assignment_is_fixed_and_utc_aligned(self):
        self.assertEqual(
            interval_for(datetime(2026, 1, 2, 14, 30, 29, 999999, tzinfo=UTC)),
            (
                datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
                datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC),
            ),
        )
        self.assertEqual(
            interval_for(datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC))[0],
            datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC),
        )

    def test_bar_ohlcv_uses_ordered_trades(self):
        event_bus, live_bus, builder = self.pipeline()
        for timestamp, price, size, trade_id in (
            ("2026-01-02T14:30:05Z", 10.0, 100, "T1"),
            ("2026-01-02T14:30:10Z", 10.4, 25, "T2"),
            ("2026-01-02T14:30:20Z", 9.8, 50, "T3"),
            ("2026-01-02T14:30:25Z", 10.2, 75, "T4"),
        ):
            live_bus.ingest(normalized_trade(t=timestamp, p=price, s=size, i=trade_id))
        builder.advance("SPY", datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC))
        event_bus.dispatch()
        bar = builder.bars[0]
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (10.0, 10.4, 9.8, 10.2))
        self.assertEqual((bar.volume, bar.trade_count), (250.0, 4))
        self.assertEqual(bar.source_trade_ids, ("T1", "T2", "T3", "T4"))
        self.assertEqual(len(bar.source_event_sequences), 4)

    def test_quotes_remain_separate_and_latest_quote_is_attached(self):
        event_bus, live_bus, builder = self.pipeline()
        live_bus.ingest(normalized_quote(bp=99.0, ap=100.0, t="2026-01-02T14:30:01Z"))
        live_bus.ingest(normalized_trade(p=10.0, t="2026-01-02T14:30:05Z"))
        live_bus.ingest(normalized_quote(bp=10.08, ap=10.12, t="2026-01-02T14:30:20Z"))
        live_bus.ingest(normalized_trade(p=10.1, t="2026-01-02T14:30:25Z"))
        builder.advance("SPY", datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC))
        event_bus.dispatch()
        bar = builder.bars[0]
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (10.0, 10.1, 10.0, 10.1))
        self.assertEqual((bar.latest_bid, bar.latest_ask), (10.08, 10.12))

    def test_closed_bar_is_exact_immutable_event_payload(self):
        event_bus, live_bus, builder = self.pipeline()
        recorder = RecordingSubscriber()
        event_bus.subscribe(THIRTY_SECOND_BAR_CLOSED, recorder)
        live_bus.ingest(normalized_trade())
        builder.advance("SPY", datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC))
        event_bus.dispatch()
        self.assertIs(recorder.events[0].payload, builder.bars[0])
        with self.assertRaises(FrozenInstanceError):
            builder.bars[0].close = 11.0  # type: ignore[misc]

    def test_closed_bar_is_not_rewritten_and_late_trade_is_recorded(self):
        event_bus, live_bus, builder = self.pipeline()
        live_bus.ingest(normalized_trade())
        builder.advance("SPY", datetime(2026, 1, 2, 14, 31, tzinfo=UTC))
        event_bus.dispatch()
        completed = builder.bars[0]
        accepted = builder.process_trade(
            normalized_trade(t="2026-01-02T14:30:10Z", i="LATE"),
            999,
        )
        self.assertFalse(accepted)
        self.assertIs(builder.bars[0], completed)
        self.assertEqual(builder.late_trade_rejections[0].trade_id, "LATE")
        self.assertEqual(builder.late_trade_rejections[0].reason, "interval_already_closed")

    def test_no_trade_interval_emits_no_fabricated_bar(self):
        event_bus, live_bus, builder = self.pipeline()
        live_bus.ingest(normalized_trade(t="2026-01-02T14:30:05Z", i="T1"))
        live_bus.ingest(normalized_trade(t="2026-01-02T14:31:05Z", i="T2"))
        builder.advance("SPY", datetime(2026, 1, 2, 14, 31, 30, tzinfo=UTC))
        event_bus.dispatch()
        self.assertEqual(
            [bar.interval_start for bar in builder.bars],
            [
                datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
                datetime(2026, 1, 2, 14, 31, tzinfo=UTC),
            ],
        )

    def test_identical_ordered_inputs_have_deterministic_semantics(self):
        def run_once():
            system_clock.set_mode(
                ClockMode.REPLAY,
                replay_start_time="2026-01-02T14:30:00+00:00",
                replay_step_seconds=0.001,
                sequence_start=1,
            )
            event_bus, live_bus, builder = self.pipeline()
            live_bus.ingest(normalized_trade(p=10.0, t="2026-01-02T14:30:05Z", i="T1"))
            live_bus.ingest(normalized_trade(p=10.2, t="2026-01-02T14:30:20Z", i="T2"))
            builder.advance("SPY", datetime(2026, 1, 2, 14, 30, 30, tzinfo=UTC))
            event_bus.dispatch()
            bar = builder.bars[0]
            return (
                bar.interval_start,
                bar.interval_end,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.trade_count,
                bar.source_trade_ids,
                bar.source_event_sequences,
                bar.created_at,
            )

        self.assertEqual(run_once(), run_once())


class TestOpeningRangeAndPriceSemantics(LiveMarketTestCase):
    def publish_bar(self, event_bus: EventBus, bar: ThirtySecondBar) -> None:
        event_bus.publish(Event.create(THIRTY_SECOND_BAR_CLOSED, bar))
        event_bus.dispatch()

    def test_opening_range_uses_only_0930_through_0935_bars(self):
        event_bus = EventBus()
        builder = OpeningRangeBuilder(event_bus)
        opening_start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
        self.publish_bar(event_bus, make_bar(opening_start - timedelta(seconds=30), high=50, low=1))
        for index in range(10):
            self.publish_bar(
                event_bus,
                make_bar(
                    opening_start + timedelta(seconds=30 * index),
                    high=10.2 + index / 10,
                    low=9.8 - index / 100,
                ),
            )
        self.publish_bar(event_bus, make_bar(opening_start + timedelta(minutes=5), high=99, low=1))
        opening_range = builder.ranges[0]
        self.assertEqual(opening_range.session_date, date(2026, 1, 2))
        self.assertEqual(opening_range.completed_bar_count, 10)
        self.assertTrue(opening_range.complete)
        self.assertAlmostEqual(opening_range.range_high, 11.1)
        self.assertAlmostEqual(opening_range.range_low, 9.71)
        self.assertEqual(len(opening_range.source_event_sequences), 10)

    def test_incomplete_opening_range_is_explicit(self):
        event_bus = EventBus()
        builder = OpeningRangeBuilder(event_bus)
        opening_start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
        self.publish_bar(event_bus, make_bar(opening_start))
        state = builder.advance("SPY", opening_start + timedelta(minutes=5))
        event_bus.dispatch()
        self.assertIsNotNone(state)
        self.assertFalse(state.complete)  # type: ignore[union-attr]

    def test_finalized_opening_range_ignores_late_opening_bar(self):
        event_bus = EventBus()
        builder = OpeningRangeBuilder(event_bus)
        opening_start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
        self.publish_bar(event_bus, make_bar(opening_start))
        state = builder.advance("SPY", opening_start + timedelta(minutes=5))
        event_bus.dispatch()
        self.publish_bar(event_bus, make_bar(opening_start + timedelta(seconds=30), high=99))
        self.assertIs(builder.ranges[0], state)
        self.assertEqual(builder.ranges[0].completed_bar_count, 1)

    def test_evaluation_window_exposes_only_0935_through_1000_bars(self):
        event_bus = EventBus()
        builder = OpeningRangeBuilder(event_bus)
        for start in (
            datetime(2026, 1, 2, 14, 29, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 14, 35, tzinfo=UTC),
            datetime(2026, 1, 2, 14, 59, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 15, 0, tzinfo=UTC),
        ):
            self.publish_bar(event_bus, make_bar(start))
        self.assertEqual(
            [bar.interval_start for bar in builder.evaluation_bars],
            [
                datetime(2026, 1, 2, 14, 35, tzinfo=UTC),
                datetime(2026, 1, 2, 14, 59, 30, tzinfo=UTC),
            ],
        )

    def test_signal_and_future_execution_references_are_locked(self):
        bar = make_bar(datetime(2026, 1, 2, 14, 35, tzinfo=UTC), high=12.0, low=8.0)
        quote = normalized_quote(bp=10.08, ap=10.12)
        next_trade = normalized_trade(p=10.15)
        self.assertEqual(completed_bar_signal_price(bar), bar.close)
        self.assertEqual(future_buy_execution_reference(quote, next_trade), 10.12)
        self.assertEqual(future_sell_execution_reference(quote, next_trade), 10.08)
        self.assertEqual(future_buy_execution_reference(None, next_trade), 10.15)
        self.assertEqual(future_sell_execution_reference(None, next_trade), 10.15)
        self.assertNotIn(12.0, (10.12, 10.08, 10.15))
        self.assertNotIn(8.0, (10.12, 10.08, 10.15))


if __name__ == "__main__":
    unittest.main()
