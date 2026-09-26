"""Focused tests for the LAUNCH-011E historical REST schema diagnostic."""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlsplit

from aegis.clock import ClockMode, system_clock
from aegis.marketdata import MassiveMessageClassification
from scripts.run_massive_historical_trade_diagnostic import (
    EVIDENCE_LABEL,
    MAX_RECORDS_PER_SYMBOL,
    SAMPLE_END_NS,
    SAMPLE_START,
    SAMPLE_START_NS,
    SAMPLE_SYMBOLS,
    HistoricalTradeFetch,
    build_historical_diagnostic,
    fetch_historical_trades,
    map_rest_trade_to_websocket,
    write_historical_diagnostic,
)


def rest_trade(**overrides: object) -> dict[str, object]:
    trade: dict[str, object] = {
        "conditions": [12, 37],
        "correction": 0,
        "decimal_size": "100.0",
        "exchange": 4,
        "id": "R1",
        "participant_timestamp": SAMPLE_START_NS + 4_000_000,
        "price": 500.25,
        "sequence_number": 7001,
        "sip_timestamp": SAMPLE_START_NS + 5_000_000,
        "size": 100,
        "tape": 3,
        "trf_id": 202,
        "trf_timestamp": SAMPLE_START_NS + 3_000_000,
    }
    trade.update(overrides)
    return trade


class TestMassiveHistoricalTradeDiagnostic(unittest.TestCase):
    def setUp(self) -> None:
        system_clock.set_mode(
            ClockMode.REPLAY,
            replay_start_time="2026-09-26T14:00:00+00:00",
            replay_step_seconds=0.001,
            sequence_start=1,
        )

    def tearDown(self) -> None:
        system_clock.set_mode(ClockMode.LIVE)

    def test_documented_rest_fields_map_to_websocket_trade_fields(self):
        original = rest_trade()
        mapped = map_rest_trade_to_websocket("SPY", original)

        self.assertEqual((mapped["ev"], mapped["sym"]), ("T", "SPY"))
        self.assertEqual((mapped["p"], mapped["s"], mapped["ds"]), (500.25, 100, "100.0"))
        self.assertEqual((mapped["x"], mapped["i"], mapped["q"], mapped["z"]), (4, "R1", 7001, 3))
        self.assertEqual(mapped["t"], (SAMPLE_START_NS + 5_000_000) // 1_000_000)
        self.assertEqual(mapped["pt"], (SAMPLE_START_NS + 4_000_000) // 1_000_000)
        self.assertEqual(mapped["trft"], (SAMPLE_START_NS + 3_000_000) // 1_000_000)
        self.assertNotIn("correction", mapped)
        self.assertEqual(original["correction"], 0)

    def test_zero_fractional_and_missing_values_are_not_sanitized(self):
        zero_fractional = map_rest_trade_to_websocket(
            "SPY",
            rest_trade(size=0, decimal_size="0.25"),
        )
        missing = rest_trade(decimal_size="0.5")
        del missing["size"]
        missing_mapped = map_rest_trade_to_websocket("SPY", missing)

        self.assertEqual(zero_fractional["s"], 0)
        self.assertEqual(zero_fractional["ds"], "0.25")
        self.assertNotIn("s", missing_mapped)
        self.assertEqual(missing_mapped["ds"], "0.5")

    def test_pagination_caps_records_strips_credentials_and_reports_truncation(self):
        calls: list[tuple[str, str]] = []
        pages = [
            {
                "results": [rest_trade(id="R1"), rest_trade(id="R2")],
                "next_url": (
                    "https://api.massive.com/v3/trades/SPY?cursor=abc&"
                    "apiKey=SHOULD_NOT_SURVIVE&limit=3"
                ),
            },
            {"results": [rest_trade(id="R3"), rest_trade(id="R4")]},
        ]

        def request_json(url: str, api_key: str):
            calls.append((url, api_key))
            return pages.pop(0)

        fetched = fetch_historical_trades(
            "SPY",
            "MEMORY_ONLY_KEY",
            request_json=request_json,
            max_records=3,
        )

        self.assertEqual([trade["id"] for trade in fetched.records], ["R1", "R2", "R3"])
        self.assertEqual(fetched.pages_requested, 2)
        self.assertTrue(fetched.truncated)
        self.assertTrue(all(api_key == "MEMORY_ONLY_KEY" for _, api_key in calls))
        self.assertTrue(all("apikey" not in url.lower() for url, _ in calls))
        first_query = parse_qs(urlsplit(calls[0][0]).query)
        second_query = parse_qs(urlsplit(calls[1][0]).query)
        self.assertEqual(first_query["timestamp.gte"], [str(SAMPLE_START_NS)])
        self.assertEqual(first_query["timestamp.lt"], [str(SAMPLE_END_NS)])
        self.assertEqual(first_query["limit"], ["3"])
        self.assertEqual(second_query["limit"], ["1"])

    def test_report_preserves_raw_records_and_reuses_existing_classifier(self):
        records_by_symbol = {
            "SPY": (
                rest_trade(id="SPY-VALID"),
                rest_trade(id="SPY-FRACTIONAL", size=0, decimal_size="0.25"),
            ),
            "NVDA": (rest_trade(id="NVDA-VALID", price=180.5),),
            "AAPL": (rest_trade(id="AAPL-VALID", price=250.5),),
        }

        def fetcher(symbol: str, api_key: str) -> HistoricalTradeFetch:
            self.assertEqual(api_key, "SECRET_NOT_FOR_ARTIFACT")
            return HistoricalTradeFetch(
                symbol=symbol,
                records=records_by_symbol[symbol],
                pages_requested=1,
                truncated=False,
            )

        report = build_historical_diagnostic(
            "SECRET_NOT_FOR_ARTIFACT",
            fetcher=fetcher,
        )

        self.assertEqual(report["evidence_label"], EVIDENCE_LABEL)
        self.assertEqual(report["fixed_sample"]["symbols"], list(SAMPLE_SYMBOLS))
        self.assertEqual(report["fixed_sample"]["maximum_records_per_symbol"], MAX_RECORDS_PER_SYMBOL)
        self.assertEqual(report["symbols"]["SPY"]["raw_trades"], list(records_by_symbol["SPY"]))
        self.assertEqual(report["symbols"]["SPY"]["raw_trades"][1]["size"], 0)
        self.assertEqual(report["symbols"]["SPY"]["raw_trades"][1]["decimal_size"], "0.25")
        self.assertEqual(report["summary"]["total_raw_records"], 4)
        self.assertEqual(report["summary"]["accepted_trades"], 3)
        self.assertEqual(report["summary"]["malformed_messages"], 1)
        self.assertEqual(report["summary"]["zero_size_positive_decimal_size_records"], 1)
        self.assertTrue(report["summary"]["counts_reconcile"])
        counts = report["classification"]["classification_counts"]
        self.assertEqual(counts[MassiveMessageClassification.ACCEPTED_TRADE.value], 3)
        self.assertEqual(counts[MassiveMessageClassification.MISSING_OR_INVALID_SIZE.value], 1)
        sample = report["classification"]["samples_by_reason"]["size_invalid"][0]
        self.assertEqual(sample["safe_market_data_fields"]["s"], 0)
        self.assertEqual(sample["safe_market_data_fields"]["ds"], "0.25")
        self.assertNotIn("SECRET_NOT_FOR_ARTIFACT", json.dumps(report))

        with TemporaryDirectory() as directory:
            output = write_historical_diagnostic(
                report,
                Path(directory) / "historical.json",
            )
            loaded = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(loaded["evidence_label"], EVIDENCE_LABEL)
        self.assertEqual(loaded["symbols"]["SPY"]["raw_trades"][0]["correction"], 0)

    def test_sensitive_response_field_is_refused_instead_of_saved(self):
        def fetcher(symbol: str, api_key: str) -> HistoricalTradeFetch:
            trade = rest_trade()
            trade["authorization"] = "must-not-be-saved"
            return HistoricalTradeFetch(
                symbol=symbol,
                records=(trade,),
                pages_requested=1,
                truncated=False,
            )

        with self.assertRaisesRegex(ValueError, "prohibited sensitive field"):
            build_historical_diagnostic("MEMORY_ONLY_KEY", fetcher=fetcher)

    def test_fixed_window_is_exactly_two_new_york_minutes(self):
        self.assertEqual(SAMPLE_END_NS - SAMPLE_START_NS, 120_000_000_000)
        self.assertEqual(SAMPLE_START.utcoffset(), timedelta(hours=-4))


if __name__ == "__main__":
    unittest.main()
