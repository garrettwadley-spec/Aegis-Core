"""Outcome observation and feedback summaries for Aegis."""

from .journal import OutcomeJournal
from .models import RecordedDecisionOutcome
from .observer import (
    EVALUATION_HORIZON,
    LEARNING_ELIGIBILITY,
    OutcomeObserver,
    evaluate_decision_outcome,
)
from .summary import FeedbackSummary, format_feedback_summary, summarize_outcomes

__all__ = [
    "EVALUATION_HORIZON",
    "FeedbackSummary",
    "LEARNING_ELIGIBILITY",
    "OutcomeJournal",
    "OutcomeObserver",
    "RecordedDecisionOutcome",
    "evaluate_decision_outcome",
    "format_feedback_summary",
    "summarize_outcomes",
]
