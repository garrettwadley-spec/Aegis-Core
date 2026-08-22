"""Append-only JSON Lines journal for paper decisions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DecisionJournal:
    """Persist complete decision records without rewriting prior entries."""

    def __init__(self, path: Path | str = "runs/decisions/decisions.jsonl") -> None:
        self.path = Path(path)

    def append(self, record: dict[str, Any]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(record, sort_keys=True) + "\n")
        return self.path
