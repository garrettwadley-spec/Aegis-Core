# Outcome Feedback

LAUNCH-006 registers an existing filled paper decision with `OutcomeObserver`,
then consumes `MarketDataReceived` events from the same canonical Market Data
Bus. The first later same-symbol event with a higher F001 sequence becomes the
`NEXT_CANONICAL_OBSERVATION` mark.

The observer calculates signed paper return, return percentage, and directional
correctness, then appends one immutable JSON object to
`runs/outcomes/outcomes.jsonl`. Decision records are never modified. Duplicate
evaluation of the same decision and horizon is prevented across process restarts.

## Feedback Summary

`summarize_outcomes()` reads the outcome journal and reports evaluated,
profitable, unprofitable, flat, directional accuracy, and cumulative signed
paper return.

These records are `PIPELINE_FEEDBACK_ONLY`. Replay prices are canonical, but the
Opening Range factors remain configured fixtures, so the records are not
strategy-profitability evidence.

## Local Demo

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1.venv\Scripts\python.exe -m scripts.run_first_outcome_feedback
```
