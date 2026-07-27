from __future__ import annotations

from aegis.execution.order_models import (
    ExecutionResult,
    ExecutionStatus,
    TradeRequest,
)
from aegis.execution.order_router import OrderRouter


class ExecutionEngine:
    """Validates and routes trade requests through the broker layer."""

    def __init__(
        self,
        router: OrderRouter,
        minimum_confidence: float = 0.0,
        maximum_quantity: int = 1_000,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0.0 and 1.0")

        if maximum_quantity <= 0:
            raise ValueError("maximum_quantity must be greater than zero")

        self.router = router
        self.minimum_confidence = minimum_confidence
        self.maximum_quantity = maximum_quantity

    def execute(self, request: TradeRequest) -> ExecutionResult:
        validation_error = self._validate(request)

        if validation_error:
            return ExecutionResult(
                status=ExecutionStatus.REJECTED,
                request=request,
                message=validation_error,
            )

        return self.router.route(request)

    def _validate(self, request: TradeRequest) -> str | None:
        if request.quantity > self.maximum_quantity:
            return (
                f"Quantity {request.quantity} exceeds the maximum allowed "
                f"quantity of {self.maximum_quantity}."
            )

        if request.confidence < self.minimum_confidence:
            return (
                f"Confidence {request.confidence:.2f} is below the minimum "
                f"required confidence of {self.minimum_confidence:.2f}."
            )

        return None