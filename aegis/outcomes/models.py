"""Immutable recorded decision outcome."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, kw_only=True)
class RecordedDecisionOutcome:
    outcome_record_id: str
    decision_record_id: str
    evaluated_at: datetime
    symbol: str
    action: str
    entry_price: float
    mark_price: float
    quantity: int
    signed_return: float
    signed_return_pct: float
    directional_correct: bool | None
    source_market_data_id: str
    source_event_sequence: int
    trace_id: str
    correlation_id: str
    evaluation_horizon: str
    input_origin: str
    learning_eligibility: str

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["evaluated_at"] = self.evaluated_at.isoformat()
        return record

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "RecordedDecisionOutcome":
        values = dict(record)
        values["evaluated_at"] = datetime.fromisoformat(values["evaluated_at"])
        return cls(**values)
