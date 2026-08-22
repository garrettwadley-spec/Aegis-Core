from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from aegis.clock import system_clock


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class ExecutionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PREVIEWED = "previewed"
    FILLED = "filled"
    FAILED = "failed"


@dataclass(frozen=True)
class TradeRequest:
    symbol: str
    quantity: int
    side: OrderSide
    strategy: str
    confidence: float = 0.0
    mode: ExecutionMode = ExecutionMode.PAPER

    def __post_init__(self) -> None:
        normalized_symbol = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", normalized_symbol)

        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")

        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        if not self.strategy.strip():
            raise ValueError("strategy cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    status: ExecutionStatus
    request: TradeRequest
    message: str
    broker_response: dict[str, Any] | None = None
    timestamp_utc: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp_utc:
            self.timestamp_utc = system_clock.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["request"]["side"] = self.request.side.value
        result["request"]["mode"] = self.request.mode.value
        return result
