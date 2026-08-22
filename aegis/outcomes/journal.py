"""Append-only journal for immutable decision outcomes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis.execution import DecisionJournal

from .models import RecordedDecisionOutcome


class OutcomeJournal(DecisionJournal):
    """Extend the existing JSONL journaling pattern with outcome deduplication."""

    def __init__(self, path: Path | str = "runs/outcomes/outcomes.jsonl") -> None:
        super().__init__(path)

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as journal:
            return [json.loads(line) for line in journal if line.strip()]

    def evaluated_keys(self) -> set[tuple[str, str]]:
        return {
            (record["decision_record_id"], record["evaluation_horizon"])
            for record in self.records()
        }

    def append_outcome(self, outcome: RecordedDecisionOutcome) -> bool:
        key = (outcome.decision_record_id, outcome.evaluation_horizon)
        if key in self.evaluated_keys():
            return False
        self.append(outcome.to_dict())
        return True

    def outcome_for(
        self,
        decision_record_id: str,
        evaluation_horizon: str,
    ) -> RecordedDecisionOutcome | None:
        for record in self.records():
            if (
                record["decision_record_id"] == decision_record_id
                and record["evaluation_horizon"] == evaluation_horizon
            ):
                return RecordedDecisionOutcome.from_dict(record)
        return None
