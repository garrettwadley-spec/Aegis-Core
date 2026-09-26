"""Exercise Massive WebSocket trade validation with fixed historical REST data."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from aegis.clock import system_clock
from aegis.marketdata import (
    MASSIVE_API_KEY,
    MassiveDataMode,
    MassiveMessageClassification,
    MassiveStockStreamAdapter,
    massive_credential_present,
)


EVIDENCE_LABEL = "HISTORICAL_REST_SCHEMA_DIAGNOSTIC"
MASSIVE_TRADES_PATH = "/v3/trades/{stockTicker}"
SAMPLE_SYMBOLS = ("SPY", "NVDA", "AAPL")
SAMPLE_TIMEZONE = ZoneInfo("America/New_York")
SAMPLE_START = datetime(2026, 9, 25, 14, 0, tzinfo=SAMPLE_TIMEZONE)
SAMPLE_END = datetime(2026, 9, 25, 14, 2, tzinfo=SAMPLE_TIMEZONE)
MAX_RECORDS_PER_SYMBOL = 10_000
MAX_PAGES_PER_SYMBOL = 20
REQUEST_TIMEOUT_SECONDS = 30

REST_TO_WEBSOCKET_FIELDS = {
    "conditions": "c",
    "decimal_size": "ds",
    "exchange": "x",
    "id": "i",
    "price": "p",
    "sequence_number": "q",
    "size": "s",
    "tape": "z",
    "trf_id": "trfi",
}
REST_TO_WEBSOCKET_TIMESTAMPS = {
    "participant_timestamp": "pt",
    "sip_timestamp": "t",
    "trf_timestamp": "trft",
}
_SENSITIVE_FIELD_NAMES = frozenset(
    {"apikey", "authorization", "cookie", "cookies", "headers"}
)


@dataclass(frozen=True)
class HistoricalTradeFetch:
    symbol: str
    records: tuple[dict[str, object], ...]
    pages_requested: int
    truncated: bool


def _unix_nanoseconds(value: datetime) -> int:
    utc_value = value.astimezone(timezone.utc)
    return int(utc_value.timestamp()) * 1_000_000_000 + utc_value.microsecond * 1_000


SAMPLE_START_NS = _unix_nanoseconds(SAMPLE_START)
SAMPLE_END_NS = _unix_nanoseconds(SAMPLE_END)


def _normalized_field_name(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _assert_no_sensitive_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _normalized_field_name(key) in _SENSITIVE_FIELD_NAMES:
                raise ValueError("diagnostic data contains a prohibited sensitive field")
            _assert_no_sensitive_fields(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_no_sensitive_fields(child)


def _nanoseconds_to_milliseconds(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value // 1_000_000
    return value


def map_rest_trade_to_websocket(
    symbol: str,
    trade: Mapping[str, object],
) -> dict[str, object]:
    """Map documented REST trade fields to documented WebSocket T fields."""

    mapped: dict[str, object] = {"ev": "T", "sym": symbol}
    for rest_field, websocket_field in REST_TO_WEBSOCKET_FIELDS.items():
        if rest_field in trade:
            mapped[websocket_field] = trade[rest_field]
    for rest_field, websocket_field in REST_TO_WEBSOCKET_TIMESTAMPS.items():
        if rest_field in trade:
            mapped[websocket_field] = _nanoseconds_to_milliseconds(
                trade[rest_field]
            )
    return mapped


def _initial_request_url(symbol: str, *, limit: int) -> str:
    path = f"/v3/trades/{quote(symbol, safe='')}"
    query = urlencode(
        {
            "timestamp.gte": str(SAMPLE_START_NS),
            "timestamp.lt": str(SAMPLE_END_NS),
            "order": "asc",
            "sort": "timestamp",
            "limit": str(limit),
        }
    )
    return urlunsplit(("https", "api.massive.com", path, query, ""))


def _bounded_next_url(next_url: object, symbol: str, *, limit: int) -> str:
    if not isinstance(next_url, str) or not next_url.strip():
        raise ValueError("Massive next_url must be a non-empty string")
    parsed = urlsplit(next_url)
    expected_path = f"/v3/trades/{quote(symbol, safe='')}"
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "api.massive.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path != expected_path
    ):
        raise ValueError("Massive next_url escaped the authorized trades endpoint")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if _normalized_field_name(key) != "apikey" and key.lower() != "limit"
    ]
    query.append(("limit", str(limit)))
    return urlunsplit(
        ("https", "api.massive.com", expected_path, urlencode(query), "")
    )


def _request_json(url: str, api_key: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Aegis-LAUNCH-011E-historical-diagnostic",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        raise RuntimeError(
            f"Massive historical request failed with HTTP {exc.code}"
        ) from None
    except URLError:
        raise RuntimeError("Massive historical request failed before a response") from None
    except (TypeError, ValueError):
        raise RuntimeError("Massive historical response was not valid JSON") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Massive historical response must be a JSON object")
    return payload


def fetch_historical_trades(
    symbol: str,
    api_key: str,
    *,
    request_json: Callable[[str, str], Mapping[str, object]] = _request_json,
    max_records: int = MAX_RECORDS_PER_SYMBOL,
) -> HistoricalTradeFetch:
    if max_records <= 0 or max_records > MAX_RECORDS_PER_SYMBOL:
        raise ValueError("max_records must be between one and 10,000")
    records: list[dict[str, object]] = []
    pages_requested = 0
    truncated = False
    request_url = _initial_request_url(symbol, limit=max_records)

    while request_url:
        if pages_requested >= MAX_PAGES_PER_SYMBOL:
            truncated = True
            break
        payload = request_json(request_url, api_key)
        pages_requested += 1
        page_records = payload.get("results", [])
        if not isinstance(page_records, list):
            raise RuntimeError("Massive historical results must be an array")
        remaining = max_records - len(records)
        for trade in page_records[:remaining]:
            if not isinstance(trade, Mapping):
                raise RuntimeError("Massive historical trade must be an object")
            copied = dict(trade)
            _assert_no_sensitive_fields(copied)
            records.append(copied)
        if len(page_records) > remaining:
            truncated = True
            break

        next_url = payload.get("next_url")
        if not next_url:
            break
        if len(records) >= max_records:
            truncated = True
            break
        request_url = _bounded_next_url(
            next_url,
            symbol,
            limit=max_records - len(records),
        )

    return HistoricalTradeFetch(
        symbol=symbol,
        records=tuple(records),
        pages_requested=pages_requested,
        truncated=truncated,
    )


def _positive_decimal(value: object) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def build_historical_diagnostic(
    api_key: str,
    *,
    fetcher: Callable[[str, str], HistoricalTradeFetch] = fetch_historical_trades,
) -> dict[str, object]:
    adapter = MassiveStockStreamAdapter(
        symbols=SAMPLE_SYMBOLS,
        observation_sink=lambda observation: None,
        api_key="historical-schema-diagnostic-placeholder",
        mode=MassiveDataMode.DELAYED_TRADES,
    )
    symbol_reports: dict[str, object] = {}
    fractional_candidates = 0
    total_raw_records = 0
    any_truncated = False

    for symbol in SAMPLE_SYMBOLS:
        fetched = fetcher(symbol, api_key)
        if fetched.symbol != symbol:
            raise ValueError("historical fetch result symbol does not match request")
        raw_records = list(fetched.records)
        total_raw_records += len(raw_records)
        any_truncated = any_truncated or fetched.truncated
        symbol_fractional_candidates = sum(
            1
            for trade in raw_records
            if trade.get("size") == 0
            and _positive_decimal(trade.get("decimal_size"))
        )
        fractional_candidates += symbol_fractional_candidates
        for trade in raw_records:
            adapter.handle_message(map_rest_trade_to_websocket(symbol, trade))
        symbol_reports[symbol] = {
            "raw_record_count": len(raw_records),
            "pages_requested": fetched.pages_requested,
            "truncated": fetched.truncated,
            "zero_size_positive_decimal_size_records": (
                symbol_fractional_candidates
            ),
            "raw_trades": raw_records,
        }

    diagnostics = adapter.diagnostic_report()
    report: dict[str, object] = {
        "evidence_label": EVIDENCE_LABEL,
        "generated_at": system_clock.now().isoformat(),
        "evidence_boundary": (
            "Historical REST records mapped through the documented WebSocket "
            "trade schema; not original WebSocket payload evidence."
        ),
        "source": {
            "transport": "HTTPS_REST",
            "endpoint_path": MASSIVE_TRADES_PATH,
            "authentication": "Bearer header used in memory and not retained",
        },
        "fixed_sample": {
            "symbols": list(SAMPLE_SYMBOLS),
            "timezone": "America/New_York",
            "start_local": SAMPLE_START.isoformat(),
            "end_local_exclusive": SAMPLE_END.isoformat(),
            "start_sip_timestamp_ns": SAMPLE_START_NS,
            "end_sip_timestamp_ns_exclusive": SAMPLE_END_NS,
            "maximum_records_per_symbol": MAX_RECORDS_PER_SYMBOL,
        },
        "schema_mapping": {
            "direct_fields": dict(REST_TO_WEBSOCKET_FIELDS),
            "timestamp_fields": dict(REST_TO_WEBSOCKET_TIMESTAMPS),
            "timestamp_conversion": "integer Unix nanoseconds to Unix milliseconds",
            "synthetic_fields": {"ev": "T", "sym": "requested stockTicker"},
            "unmapped_rest_fields_preserved_in_raw_records": ["correction"],
        },
        "summary": {
            "total_raw_records": total_raw_records,
            "any_symbol_truncated": any_truncated,
            "zero_size_positive_decimal_size_records": fractional_candidates,
            "accepted_trades": adapter.message_diagnostics.count(
                MassiveMessageClassification.ACCEPTED_TRADE
            ),
            "malformed_messages": adapter.status.malformed_messages,
            "delivery_failures": adapter.message_diagnostics.delivery_failures,
            "counts_reconcile": adapter.message_diagnostics.counts_reconcile,
        },
        "classification": diagnostics,
        "symbols": symbol_reports,
    }
    _assert_no_sensitive_fields(report)
    serialized = json.dumps(report, sort_keys=True)
    if api_key and api_key in serialized:
        raise RuntimeError("credential value reached diagnostic output")
    return report


def write_historical_diagnostic(
    report: Mapping[str, object],
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _default_output_path() -> Path:
    stamp = system_clock.now().strftime("%Y%m%d-%H%M%S")
    return Path("runs/massive_diagnostics") / f"historical-rest-{stamp}.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    print(EVIDENCE_LABEL)
    if not massive_credential_present():
        print("MASSIVE_API_KEY is not present in the local process environment.")
        print("HISTORICAL REST DIAGNOSTIC: BLOCKED_BY_MISSING_CREDENTIAL")
        return 2

    report = build_historical_diagnostic(os.environ[MASSIVE_API_KEY])
    output_path = write_historical_diagnostic(
        report,
        args.output or _default_output_path(),
    )
    summary = report["summary"]
    symbols = report["symbols"]
    for symbol in SAMPLE_SYMBOLS:
        item = symbols[symbol]
        print(
            f"{symbol}: records={item['raw_record_count']} "
            f"pages={item['pages_requested']} truncated={item['truncated']}"
        )
    print(f"Total raw records: {summary['total_raw_records']}")
    print(f"Accepted trades: {summary['accepted_trades']}")
    print(f"Malformed messages: {summary['malformed_messages']}")
    print(f"Delivery failures: {summary['delivery_failures']}")
    print(f"Counts reconcile: {summary['counts_reconcile']}")
    for classification, count in report["classification"][
        "classification_counts"
    ].items():
        print(f"Classification {classification}: {count}")
    print(
        "Zero-size positive-decimal-size records: "
        f"{summary['zero_size_positive_decimal_size_records']}"
    )
    print(f"Diagnostic artifact: {output_path.resolve()}")
    print("WEBSOCKET CORRECTNESS CERTIFIED: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
