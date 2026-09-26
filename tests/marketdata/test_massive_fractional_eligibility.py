"""Focused LAUNCH-011F fractional quantity and bar-eligibility regressions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from aegis.clock import ClockMode, system_clock
from aegis.eventbus import EventBus
from aegis.marketdata import (
    LiveMarketDataBus,
    LiveTrade,
    MassiveDataMode,
    MassiveMessageClassification,
    MassiveStockStreamAdapter,
    ThirtySecondBarBuilder,
    normalize_massive_message,
)


UTC = timezone.utc
BASE_TIME = datetime(2026, 9, 25, 18, 0, tzinfo=UTC)
_MISSING = object()


def milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def trade_message(
    *,
    offset_seconds: int = 5,
    price: float = 100.0,
    size: object = 100,
    decimal_size: object = _MISSING,
    conditions: object = (),
    trade_id: str = "T1",
) -> dict[str, object]:
    message: dict[str, object] = {
        "ev": "T",
        "sym": "SPY",
        "p": price,
        "s": size,
        "x": 4,
        "i": trade_id,
        "c": list(conditions),
        "t": milliseconds(BASE_TIME + timedelta(seconds=offset_seconds)),
        "q": 7000 + offset_seconds,
        "z": 3,
    }
    if decimal_size is not _MISSING:
        message["ds"] = decimal_size
    return message


class TestMassiveFractionalEligibility(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-09-25T18:05:00+00:00",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def adapter(self, sink=None) -> MassiveStockStreamAdapter:
        return MassiveStockStreamAdapter(
            symbols=("SPY",),
            observation_sink=(lambda item: None) if sink is None else sink,
            api_key="test-key",
            mode=MassiveDataMode.DELAYED_TRADES,
        )

    def pipeline(self):
        event_bus = EventBus()
        live_bus = LiveMarketDataBus(event_bus)
        builder = ThirtySecondBarBuilder(event_bus)
        delivered: list[LiveTrade] = []

        def sink(item: LiveTrade) -> None:
            delivered.append(item)
            live_bus.ingest(item)

        return event_bus, builder, delivered, self.adapter(sink)

    def test_decimal_size_precedes_integer_size_without_mutating_input(self):
        cases = (
            (0, "0.25", Decimal("0.25"), 0.25, "ds"),
            (100, "100.25", Decimal("100.25"), 100.25, "ds"),
            (100, _MISSING, Decimal("100"), 100.0, "s"),
        )
        for size, decimal_size, exact, public_size, source in cases:
            with self.subTest(size=size, decimal_size=decimal_size):
                message = trade_message(
                    size=size,
                    decimal_size=decimal_size,
                    conditions=(37,) if decimal_size != _MISSING else (),
                )
                original = deepcopy(message)
                trade = self.adapter().handle_message(message)

                self.assertIsInstance(trade, LiveTrade)
                self.assertEqual(trade.exact_size, exact)
                self.assertEqual(trade.size, public_size)
                self.assertEqual(trade.metadata["effective_quantity_source"], source)
                self.assertEqual(trade.metadata["provider_size"], size)
                self.assertEqual(message, original)
                with self.assertRaises(TypeError):
                    trade.metadata["provider_size"] = 999  # type: ignore[index,union-attr]

    def test_invalid_present_decimal_size_never_falls_back_to_integer_size(self):
        for value in ("bad", "NaN", "Infinity", "0", "-0.25", None, False):
            with self.subTest(decimal_size=value):
                adapter = self.adapter()
                result = adapter.handle_message(
                    trade_message(size=100, decimal_size=value)
                )

                self.assertIsNone(result)
                self.assertEqual(
                    adapter.message_diagnostics.count(
                        MassiveMessageClassification.MISSING_OR_INVALID_SIZE
                    ),
                    1,
                )
                sample = adapter.diagnostic_report()["samples_by_reason"][
                    "decimal_size_invalid"
                ][0]
                self.assertEqual(sample["offending_field"], "ds")

    def test_zero_legacy_size_without_decimal_size_is_rejected(self):
        adapter = self.adapter()
        self.assertIsNone(adapter.handle_message(trade_message(size=0)))
        self.assertEqual(
            adapter.message_diagnostics.count(
                MassiveMessageClassification.MISSING_OR_INVALID_SIZE
            ),
            1,
        )

    def test_condition_combination_uses_any_false_as_precedence(self):
        odd_lot = normalize_massive_message(
            trade_message(conditions=(14, 37, 41), decimal_size="0.25", size=0)
        )
        regular = normalize_massive_message(
            trade_message(conditions=(14, 41))
        )
        average_derived = normalize_massive_message(
            trade_message(conditions=(2, 10, 41))
        )
        qualified_contingent = normalize_massive_message(
            trade_message(conditions=(41, 52, 53))
        )

        self.assertEqual(
            (odd_lot.updates_high_low, odd_lot.updates_open_close, odd_lot.updates_volume),
            (False, False, True),
        )
        self.assertEqual(
            (regular.updates_high_low, regular.updates_open_close, regular.updates_volume),
            (True, True, True),
        )
        self.assertEqual(
            (
                average_derived.updates_high_low,
                average_derived.updates_open_close,
                average_derived.updates_volume,
            ),
            (False, False, True),
        )
        self.assertEqual(
            (
                qualified_contingent.updates_high_low,
                qualified_contingent.updates_open_close,
                qualified_contingent.updates_volume,
            ),
            (False, False, True),
        )

    def test_saved_sample_conditions_use_documented_consolidated_rules(self):
        expected = {
            2: (False, False, True),
            10: (True, False, True),
            14: (True, True, True),
            37: (False, False, True),
            41: (True, True, True),
            52: (False, False, True),
            53: (False, False, True),
        }
        for condition, eligibility in expected.items():
            with self.subTest(condition=condition):
                trade = normalize_massive_message(
                    trade_message(conditions=(condition,))
                )
                self.assertEqual(
                    (
                        trade.updates_high_low,
                        trade.updates_open_close,
                        trade.updates_volume,
                    ),
                    eligibility,
                )

    def test_fractional_odd_lot_updates_exact_volume_but_not_ohlc(self):
        event_bus, builder, delivered, adapter = self.pipeline()
        adapter.handle_message(trade_message(price=100.0, trade_id="REGULAR-1"))
        adapter.handle_message(
            trade_message(
                offset_seconds=10,
                price=1000.0,
                size=0,
                decimal_size="0.25",
                conditions=(37,),
                trade_id="ODD-LOT",
            )
        )
        adapter.handle_message(
            trade_message(
                offset_seconds=20,
                price=101.0,
                trade_id="REGULAR-2",
            )
        )
        builder.advance("SPY", BASE_TIME + timedelta(seconds=30))
        event_bus.dispatch()

        bar = builder.bars[0]
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (100.0, 101.0, 100.0, 101.0))
        self.assertEqual(bar.volume, 200.25)
        self.assertEqual(bar.metadata["exact_volume_decimal"], "200.25")
        self.assertEqual(bar.source_trade_ids, ("REGULAR-1", "ODD-LOT", "REGULAR-2"))
        self.assertEqual(len(bar.source_event_sequences), 3)
        self.assertEqual(delivered[1].conditions, ("37",))
        self.assertEqual(len(builder.eligibility_exclusions), 1)
        self.assertEqual(adapter.status.malformed_messages, 0)

    def test_volume_only_interval_is_retained_without_inventing_a_candle(self):
        event_bus, builder, _, adapter = self.pipeline()
        adapter.handle_message(
            trade_message(
                size=0,
                decimal_size="0.25",
                conditions=(37,),
                trade_id="F1",
            )
        )
        adapter.handle_message(
            trade_message(
                offset_seconds=20,
                size=0,
                decimal_size="0.50",
                conditions=(37,),
                trade_id="F2",
            )
        )
        builder.advance("SPY", BASE_TIME + timedelta(seconds=30))
        event_bus.dispatch()

        self.assertEqual(builder.bars, ())
        interval = builder.incomplete_intervals[0]
        self.assertEqual(interval.exact_volume, Decimal("0.75"))
        self.assertEqual(interval.missing_fields, ("open", "high", "low", "close"))
        self.assertEqual(interval.source_trade_ids, ("F1", "F2"))
        self.assertEqual(len(interval.source_event_sequences), 2)

    def test_unknown_condition_is_accepted_but_explicitly_bar_ineligible(self):
        event_bus, builder, delivered, adapter = self.pipeline()
        adapter.handle_message(trade_message(conditions=(999,), trade_id="UNKNOWN"))
        builder.advance("SPY", BASE_TIME + timedelta(seconds=30))
        event_bus.dispatch()

        self.assertEqual(adapter.status.malformed_messages, 0)
        self.assertEqual(delivered[0].unresolved_conditions, ("999",))
        self.assertEqual(builder.bars, ())
        self.assertEqual(builder.incomplete_intervals[0].exact_volume, Decimal("0"))
        self.assertEqual(
            builder.eligibility_exclusions[0].reason,
            "unresolved_conditions",
        )

    def test_parser_diagnostic_counts_still_reconcile(self):
        adapter = self.adapter()
        adapter.handle_message(
            trade_message(size=0, decimal_size="0.25", conditions=(37,))
        )
        adapter.handle_message(trade_message(size=100, decimal_size="bad"))
        adapter.handle_message(trade_message(size=0))

        diagnostics = adapter.message_diagnostics
        self.assertEqual(diagnostics.messages_received, 3)
        self.assertEqual(
            diagnostics.count(MassiveMessageClassification.ACCEPTED_TRADE),
            1,
        )
        self.assertEqual(
            diagnostics.count(
                MassiveMessageClassification.MISSING_OR_INVALID_SIZE
            ),
            2,
        )
        self.assertTrue(diagnostics.counts_reconcile)
        self.assertTrue(diagnostics.malformed_counts_reconcile)


if __name__ == "__main__":
    unittest.main()
