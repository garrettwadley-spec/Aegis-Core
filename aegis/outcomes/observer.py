"""Observe the first eligible canonical mark after a paper decision."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from aegis.clock import system_clock
from aegis.eventbus import Event, Subscriber
from aegis.execution import RecordedPaperDecision
from aegis.marketdata import MarketData

from .journal import OutcomeJournal
from .models import RecordedDecisionOutcome


EVALUATION_HORIZON = "NEXT_CANONICAL_OBSERVATION"
LEARNING_ELIGIBILITY = "PIPELINE_FEEDBACK_ONLY"


def evaluate_decision_outcome(
    decision_record: Mapping[str, Any],
    market_data: MarketData,
    source_event_sequence: int,
) -> RecordedDecisionOutcome:
    action = str(decision_record["strategy_action"]).upper()
    entry_price = float(decision_record["fill_price"])
    mark_price = float(market_data.last)
    quantity = int(decision_record["fill_quantity"])
    if action == "BUY":
        signed_return = (mark_price - entry_price) * quantity
    elif action == "SELL":
        signed_return = (entry_price - mark_price) * quantity
    else:
        raise ValueError(f"unsupported outcome action {action}")

    signed_return_pct = signed_return / (entry_price * quantity)
    directional_correct = None if mark_price == entry_price else signed_return > 0
    decision_record_id = str(decision_record["decision_record_id"])
    outcome_key = (
        f"{decision_record_id}|{EVALUATION_HORIZON}|"
        f"{market_data.object_id}|{source_event_sequence}"
    )
    return RecordedDecisionOutcome(
        outcome_record_id=(
            f"OUTCOME-{sha256(outcome_key.encode()).hexdigest()[:16].upper()}"
        ),
        decision_record_id=decision_record_id,
        evaluated_at=system_clock.now(),
        symbol=str(decision_record["symbol"]),
        action=action,
        entry_price=entry_price,
        mark_price=mark_price,
        quantity=quantity,
        signed_return=signed_return,
        signed_return_pct=signed_return_pct,
        directional_correct=directional_correct,
        source_market_data_id=market_data.object_id,
        source_event_sequence=source_event_sequence,
        trace_id=str(decision_record["trace_id"]),
        correlation_id=str(decision_record["correlation_id"]),
        evaluation_horizon=EVALUATION_HORIZON,
        input_origin=str(decision_record["input_origin"]),
        learning_eligibility=str(
            decision_record.get("learning_eligibility", LEARNING_ELIGIBILITY)
        ),
    )


class OutcomeObserver(Subscriber):
    """Match filled decisions to their first later same-symbol market event."""

    def __init__(self, journal: OutcomeJournal) -> None:
        self._journal = journal
        self._pending: dict[str, dict[str, Any]] = {}
        self._evaluated = journal.evaluated_keys()
        self._outcomes: list[RecordedDecisionOutcome] = []

    @property
    def outcomes(self) -> tuple[RecordedDecisionOutcome, ...]:
        return tuple(self._outcomes)

    def observe_decision(
        self,
        decision: RecordedPaperDecision | Mapping[str, Any],
    ) -> bool:
        record = (
            decision.record
            if isinstance(decision, RecordedPaperDecision)
            else dict(decision)
        )
        decision_record_id = str(record["decision_record_id"])
        key = (decision_record_id, EVALUATION_HORIZON)
        if record.get("status") != "filled" or key in self._evaluated:
            return False
        self._pending[decision_record_id] = record
        return True

    def receive(self, event: Event) -> None:
        sequence = event.sequence_number
        if sequence is None:
            return
        market_data = event.payload

        for decision_record_id, record in tuple(self._pending.items()):
            if market_data.symbol != record["symbol"]:
                continue
            decision_sequence = max(record["source_event_sequences"])
            if sequence <= decision_sequence:
                continue

            outcome = evaluate_decision_outcome(record, market_data, sequence)
            if self._journal.append_outcome(outcome):
                self._outcomes.append(outcome)
            self._evaluated.add((decision_record_id, EVALUATION_HORIZON))
            del self._pending[decision_record_id]
