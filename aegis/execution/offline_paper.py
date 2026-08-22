"""Minimal offline paper execution and decision recording."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any

from aegis.execution.decision_journal import DecisionJournal
from aegis.execution.execution_engine import ExecutionEngine
from aegis.execution.order_models import (
    ExecutionMode,
    ExecutionResult,
    ExecutionStatus,
    OrderSide,
    TradeRequest,
)
from aegis.execution.order_router import OrderRouter
from aegis.marketdata import MarketData
from aegis.snapshot import MarketSnapshot
from aegis.strategies import MarketSignal


INPUT_ORIGIN = "DETERMINISTIC_REPLAY_WITH_CONFIGURED_STRATEGY_FACTORS"


class OfflinePaperBroker:
    """Fill paper orders deterministically from canonical reference prices."""

    def __init__(self, reference_prices: Mapping[str, float]) -> None:
        self._reference_prices = {
            symbol.strip().upper(): float(price)
            for symbol, price in reference_prices.items()
        }

    def preview_equity_order(
        self,
        symbol: str,
        quantity: int,
        action: str = "BUY",
    ) -> dict[str, Any]:
        normalized_symbol = symbol.strip().upper()
        normalized_action = action.strip().upper()
        price = self._reference_prices.get(normalized_symbol)
        if price is None:
            return {
                "status_code": 404,
                "ok": False,
                "raw": f"No paper reference price for {normalized_symbol}",
            }
        if normalized_action not in {"BUY", "SELL"}:
            return {
                "status_code": 400,
                "ok": False,
                "raw": f"Unsupported paper action {normalized_action}",
            }

        order_key = (
            f"{normalized_symbol}|{normalized_action}|{quantity}|{price:.10f}"
        )
        paper_order_id = f"PAPER-{sha256(order_key.encode()).hexdigest()[:16].upper()}"
        return {
            "status_code": 200,
            "ok": True,
            "status": ExecutionStatus.FILLED.value,
            "simulation": True,
            "paper_order_id": paper_order_id,
            "symbol": normalized_symbol,
            "side": normalized_action,
            "fill_quantity": quantity,
            "fill_price": price,
        }


class SignalToTradeBridge:
    """Convert actionable existing signals into one-share PAPER requests."""

    def __init__(self, quantity: int = 1) -> None:
        if quantity <= 0:
            raise ValueError("paper quantity must be greater than zero")
        self._quantity = quantity

    def create_request(self, signal: MarketSignal | None) -> TradeRequest | None:
        if signal is None or not signal.is_valid:
            return None
        if signal.action not in {OrderSide.BUY.value, OrderSide.SELL.value}:
            return None
        return TradeRequest(
            symbol=signal.symbol,
            quantity=self._quantity,
            side=OrderSide(signal.action),
            strategy=signal.strategy,
            confidence=signal.confidence,
            mode=ExecutionMode.PAPER,
        )


class LaunchSafetyGate:
    """Apply only the minimum safety checks required before paper execution."""

    @staticmethod
    def validate(
        request: TradeRequest,
        reference_price: float,
        signal: MarketSignal,
    ) -> None:
        if request.mode != ExecutionMode.PAPER:
            raise ValueError("launch execution mode must be PAPER")
        if request.quantity <= 0:
            raise ValueError("launch quantity must be greater than zero")
        if not request.symbol.strip():
            raise ValueError("launch symbol cannot be empty")
        if not isfinite(reference_price) or reference_price <= 0:
            raise ValueError("reference price must be finite and positive")
        if not signal.is_valid:
            raise ValueError("signal must be actionable")


@dataclass(frozen=True)
class RecordedPaperDecision:
    request: TradeRequest
    execution_result: ExecutionResult
    record: dict[str, Any]
    record_path: Path


class PaperDecisionService:
    """Safely execute and durably record one existing strategy signal."""

    def __init__(
        self,
        journal: DecisionJournal,
        quantity: int = 1,
    ) -> None:
        self._journal = journal
        self._bridge = SignalToTradeBridge(quantity=quantity)

    def execute(
        self,
        signal: MarketSignal | None,
        snapshot: MarketSnapshot,
    ) -> RecordedPaperDecision | None:
        request = self._bridge.create_request(signal)
        if request is None or signal is None:
            return None

        market_data, source_sequence = self._current_record(
            snapshot,
            request.symbol,
        )
        try:
            LaunchSafetyGate.validate(request, market_data.last, signal)
        except ValueError as exc:
            result = ExecutionResult(
                status=ExecutionStatus.REJECTED,
                request=request,
                message=str(exc),
            )
        else:
            broker = OfflinePaperBroker({request.symbol: market_data.last})
            engine = ExecutionEngine(
                router=OrderRouter(broker),
                minimum_confidence=0.0,
                maximum_quantity=request.quantity,
            )
            result = engine.execute(request)

        record = self._record(
            signal,
            snapshot,
            market_data,
            source_sequence,
            request,
            result,
        )
        record_path = self._journal.append(record)
        return RecordedPaperDecision(request, result, record, record_path)

    @staticmethod
    def _current_record(
        snapshot: MarketSnapshot,
        symbol: str,
    ) -> tuple[MarketData, int]:
        for market_data, sequence in zip(
            snapshot.market_data,
            snapshot.source_event_sequences,
        ):
            if market_data.symbol == symbol:
                return market_data, sequence
        raise ValueError(f"snapshot does not contain signal symbol {symbol}")

    @staticmethod
    def _record(
        signal: MarketSignal,
        snapshot: MarketSnapshot,
        market_data: MarketData,
        source_sequence: int,
        request: TradeRequest,
        result: ExecutionResult,
    ) -> dict[str, Any]:
        broker_response = result.broker_response or {}
        paper_order_id = broker_response.get("paper_order_id")
        decision_key = "|".join(
            (
                result.timestamp_utc,
                request.symbol,
                request.side.value,
                str(request.quantity),
                str(paper_order_id),
            )
        )
        decision_record_id = (
            f"DECISION-{sha256(decision_key.encode()).hexdigest()[:16].upper()}"
        )
        trade_request = {
            "symbol": request.symbol,
            "quantity": request.quantity,
            "side": request.side.value,
            "strategy": request.strategy,
            "confidence": request.confidence,
            "mode": request.mode.value,
        }
        return {
            "decision_record_id": decision_record_id,
            "timestamp": result.timestamp_utc,
            "symbol": request.symbol,
            "strategy_name": signal.strategy,
            "strategy_action": signal.action,
            "strategy_confidence": signal.confidence,
            "market_snapshot_id": snapshot.object_id,
            "market_snapshot_as_of": snapshot.as_of.isoformat(),
            "market_data_id": market_data.object_id,
            "market_data_received_at": market_data.received_at.isoformat(),
            "source_event_sequences": [source_sequence],
            "trade_request": trade_request,
            "execution_mode": request.mode.value,
            "execution_result": result.to_dict(),
            "paper_order_id": paper_order_id,
            "fill_quantity": broker_response.get("fill_quantity"),
            "fill_price": broker_response.get("fill_price"),
            "status": result.status.value,
            "trace_id": snapshot.trace_id,
            "correlation_id": snapshot.correlation_id,
            "input_origin": INPUT_ORIGIN,
        }
