from __future__ import annotations

from typing import Protocol

from aegis.execution.order_models import (
    ExecutionMode,
    ExecutionResult,
    ExecutionStatus,
    TradeRequest,
)


class BrokerProtocol(Protocol):
    def preview_equity_order(
        self,
        symbol: str,
        quantity: int,
        action: str = "BUY",
    ) -> dict:
        ...


class OrderRouter:
    """Routes approved trade requests to the configured broker."""

    def __init__(self, broker: BrokerProtocol) -> None:
        self.broker = broker

    def route(self, request: TradeRequest) -> ExecutionResult:
        if request.mode == ExecutionMode.LIVE:
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                request=request,
                message="Live execution is disabled.",
            )

        try:
            response = self.broker.preview_equity_order(
                symbol=request.symbol,
                quantity=request.quantity,
                action=request.side.value,
            )
        except Exception as exc:
            return self._simulate_paper_preview(
                request=request,
                reason=f"Broker exception: {exc}",
            )

        if response.get("ok"):
            filled = response.get("status") == ExecutionStatus.FILLED.value
            return ExecutionResult(
                status=(
                    ExecutionStatus.FILLED
                    if filled
                    else ExecutionStatus.PREVIEWED
                ),
                request=request,
                message=(
                    "Offline paper order filled."
                    if filled
                    else "Order preview accepted by broker."
                ),
                broker_response=response,
            )

        status_code = response.get("status_code")
        raw_response = str(response.get("raw", ""))

        sandbox_unavailable = (
            status_code == 500
            and "requested service is not currently available"
            in raw_response.lower()
        )

        if request.mode == ExecutionMode.PAPER and sandbox_unavailable:
            return self._simulate_paper_preview(
                request=request,
                reason="E*TRADE sandbox preview service unavailable.",
            )

        return ExecutionResult(
            status=ExecutionStatus.FAILED,
            request=request,
            message=f"Broker preview failed with HTTP status {status_code}.",
            broker_response=response,
        )

    @staticmethod
    def _simulate_paper_preview(
        request: TradeRequest,
        reason: str,
    ) -> ExecutionResult:
        simulated_response = {
            "status_code": 200,
            "ok": True,
            "simulation": True,
            "symbol": request.symbol,
            "quantity": request.quantity,
            "side": request.side.value,
            "reason": reason,
        }

        return ExecutionResult(
            status=ExecutionStatus.PREVIEWED,
            request=request,
            message="Paper order preview simulated successfully.",
            broker_response=simulated_response,
        )
