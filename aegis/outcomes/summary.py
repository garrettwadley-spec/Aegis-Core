"""Tiny read-only feedback summary for recorded outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .journal import OutcomeJournal


@dataclass(frozen=True)
class FeedbackSummary:
    evaluated: int
    profitable: int
    unprofitable: int
    flat: int
    directional_accuracy: float | None
    cumulative_signed_return: float


def summarize_outcomes(
    path: Path | str = "runs/outcomes/outcomes.jsonl",
) -> FeedbackSummary:
    records = OutcomeJournal(path).records()
    profitable = sum(record["signed_return"] > 0 for record in records)
    unprofitable = sum(record["signed_return"] < 0 for record in records)
    flat = sum(record["signed_return"] == 0 for record in records)
    directional = [
        record["directional_correct"]
        for record in records
        if record["directional_correct"] is not None
    ]
    accuracy = (
        sum(value is True for value in directional) / len(directional)
        if directional
        else None
    )
    return FeedbackSummary(
        evaluated=len(records),
        profitable=profitable,
        unprofitable=unprofitable,
        flat=flat,
        directional_accuracy=accuracy,
        cumulative_signed_return=sum(
            float(record["signed_return"]) for record in records
        ),
    )


def format_feedback_summary(summary: FeedbackSummary) -> str:
    accuracy = (
        "N/A"
        if summary.directional_accuracy is None
        else f"{summary.directional_accuracy:.2%}"
    )
    paper_return = (
        f"+${summary.cumulative_signed_return:.2f}"
        if summary.cumulative_signed_return >= 0
        else f"-${abs(summary.cumulative_signed_return):.2f}"
    )
    return "\n".join(
        (
            f"Evaluated: {summary.evaluated}",
            f"Profitable: {summary.profitable}",
            f"Unprofitable: {summary.unprofitable}",
            f"Flat: {summary.flat}",
            f"Directional Accuracy: {accuracy}",
            f"Paper Return: {paper_return}",
        )
    )
