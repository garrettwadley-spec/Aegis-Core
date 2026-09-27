# AEGIS — Canonical Recovery & Handoff

**Recovery date:** 2026-09-26  
**Purpose:** Preserve the verified AEGIS state after the "AEGIS Main Build" chat exhausted its context before the planned backup/handoff was run.

## Evidence classes
- **VERIFIED — REPOSITORY:** confirmed on current GitHub main.
- **VERIFIED — PROJECT ARTIFACT:** confirmed in persistent blueprint/project artifacts.
- **RECOVERED — PROJECT RECORD:** retained project decision/context, not necessarily implemented on main.
- **NOT RECOVERED:** known/discussed but not found in current persistent sources.

## Repository
- Legacy URL: `garrettwadley-spec/cloud-trader`
- Current repository: `garrettwadley-spec/Aegis-Core`
- Branch: `main`
- Verified head: `ca7e08a7908d1367f67c2ce0029fd61cd906a598`
- Head message: `feat(execution): add paper execution engine and order routing`
- Head date: 2026-07-26 Central / 2026-07-27 UTC

The repository head predates later Main Build design work. GitHub is therefore not the complete record of the final chat state.

## Canonical mission
AEGIS is a single-mind AI trading platform. AI owns interpretation, RAG, synthesis, research, strategy specification and rationale. Deterministic services own market calculations, policy, risk, authoritative state, order lifecycle, broker interaction and auditability. Learning may propose changes but cannot mutate production behavior without a gated promotion path.

## Master blueprint
Recovered blueprint date: 2025-09-13.

Original phases:
1. Phase 0 — Base Setup
2. Phase 1 — RAG + Policy
3. Phase 2 — LoRA Fine-Tuning
4. Phase 3 — Continuous Learning
5. Phase 4 — Executor / Live Trading

Historical gate examples such as Sharpe >= 1.1 and MaxDD <= 20% remain design examples, not approved production thresholds.

## State -> Trigger correction
**RECOVERED — PROJECT RECORD**

- **State:** setup is eligible for consideration.
- **Trigger:** directional confirmation that movement has begun.

Structural rule: **State is not an entry. Trigger is required.**

The current repository does NOT encode this separation. Current `aegis/strategies/opening_range.py` still combines relative volume, price change, RSI and MACD-cross conditions in one Boolean entry block. Later State->Trigger backtest work therefore did not reach current `main`.

## Verified repository milestones

### 022bb0b
`Aegis baseline: orchestrator, tools, policy, multi-run engine`

### 20996eb
`Create canonical aegis runtime structure`

### 0ad17e6
`Move orchestrator into aegis/api`

### 69b3ca9
`add data pipeline scripts and ignore generated datasets`

Recovered features include returns, rolling volatility, MA5/MA20, trend, volume-spike ratio and intrabar range.

### 781ec04
`feat(etrade): establish broker foundation and project memory`

Verified broker path:
`aegis/capabilities/brokers/etrade/broker.py`

Verified methods:
- accounts
- quote
- positions
- balances
- orders
- preview_equity_order

### 37a24b6
`feat(strategy): complete strategy-to-execution paper pipeline`

Created:
- `aegis/strategies/signal.py`
- `aegis/strategies/strategy_base.py`
- `aegis/strategies/opening_range.py`
- `test_strategy.py`
- `test_strategy_execution_pipeline.py`

### ca7e08a
Current verified main head.

Created:
- `aegis/execution/__init__.py`
- `aegis/execution/execution_engine.py`
- `aegis/execution/order_models.py`
- `aegis/execution/order_router.py`
- `test_execution_engine.py`

## Current execution state
Verified:
- `TradeRequest`
- PAPER / LIVE modes
- ACCEPTED / REJECTED / PREVIEWED / FAILED result states
- maximum quantity validation
- minimum confidence validation
- E*TRADE preview routing
- PAPER simulation fallback
- LIVE explicitly rejected

This is NOT a production OMS.

Missing:
- authoritative order state machine
- idempotency guarantees
- partial fills
- cancel/replace
- persistent order store
- reconciliation loop
- restart recovery
- position reconstruction
- duplicate event handling
- live order placement
- portfolio-level risk gate
- external kill-switch enforcement

## Current orchestrator
Path:
`aegis/api/orchestrator.py`

Verified endpoints:
- `/health`
- `/runs`
- `/runs/{run_id}`
- `/ask`
- `/multi-run`
- `/multi-run/{run_id}`

Registered tools:
- `data.fetch`
- `backtest.run`
- `train.run`
- `risk.simulate`

## P0 policy defect
Current orchestrator checks:

```python
POLICY.get("allowed_tools", [])
POLICY.get("denied_tools", [])
```

Current `aegis/config/policy.yaml` uses:

```yaml
tools:
  allow:
    - backtest.run
    - plot.equity
    - run_and_plot
    - run_and_plot_save
    - strategy.run
  deny: []
```

Therefore the configured allow/deny schema is not being read by `allowed_tool()`. With `allowed_tools` absent, the allow-list restriction is effectively bypassed. Treat as a high-priority control defect.

## Engineering Constitution
AEGIS adopted Architecture v1.0 and a 150-rule Engineering Constitution. The complete exact 150-rule wording was not consolidated into one canonical repository file before chat exhaustion.

Exact recoverable rules:
- **#50 — Outcome Evaluation Is Independent**
- **#76 — Every External Event Requires Reconciliation**
- **#77 — Broker Independence**
- **#78 — Canonical Translation**
- **#87 — Cross-Cutting Services Never Own Business Logic**
- **#102 — Deterministic Core**
- **#119 — Architecture Review Board**
- **#120 — Architecture Baselines Are Immutable**
- **#121 — Every Change Must Improve the System**

Confirmed themes:
architecture first, single ownership, explicit contracts, determinism, immutable history, explainability, outcome independence, broker reconciliation, broker independence, learning isolation, human authority, architecture review and self-review.

Do not invent missing Constitution wording and present it as original.

## Recovered workflow
Canonical engineering sequence:

**ARCHITECTURE -> INTERFACE -> IMPLEMENTATION -> TEST -> COMMIT**

Additional recovered working rules:
- test before commit
- prefer full-file updates over patch-style edits
- operational checks must include exact user steps
- avoid long uncommitted work stretches
- preserve checkpoints

Prior checkpoint:
`checkpoint-2-strategy-pipeline` at `37a24b6`.

## Recovered Stage-1 dependency order
1. Mission
2. Policy
3. Market Data
4. Scanner
5. Ranking
6. Risk
7. Trade Planner
8. Order Lifecycle
9. Position Manager
10. State Database
11. Evaluation
12. Event Loop
13. Dashboard

## Main Build work not recovered in GitHub
Later project context shows active work on `backtest_run.py` to test State->Trigger. The user requested complete-file updates instead of patches and referenced working from:

`C:\Users\garre\cloud-trader`

That later file is not present at the checked repository root on current `main`.

Highest-priority remaining recovery source: the user's local working tree.

## Non-destructive local recovery commands

```powershell
cd C:\Users\garre\cloud-trader

git status
git branch --show-current
git log --oneline -10

git status --short
git diff
git diff --staged

Get-ChildItem -Path C:\Users\garre\cloud-trader -Recurse -File -Filter "backtest_run.py" |
    Select-Object FullName, LastWriteTime, Length

Get-ChildItem -Path C:\Users\garre\cloud-trader -Recurse -File -Include *.py |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 40 FullName, LastWriteTime, Length

Get-ChildItem -Path C:\Users\garre\cloud-trader -Recurse -File -Include *.py,*.md,*.txt |
    Select-String -Pattern "State|Trigger|state|trigger|momentum confirmation|MACD" |
    Select-Object Path, LineNumber, Line

git stash list
git reflog --date=local -30
```

Until recovery is complete, do NOT run:
- `git reset --hard`
- `git clean -fd`
- `git checkout -- .`
- `git restore .`
- `git pull --rebase`

## Current critical gaps

### P0
1. Policy schema mismatch.
2. State->Trigger design absent from current strategy code.
3. No production OMS.
4. Local code may be ahead of GitHub and must be preserved before repair.

### P1
1. Risk layer limited to confidence and quantity.
2. E*TRADE credential path is machine-specific (`C:\AITrader\.env`).
3. Broker HTTP calls lack explicit institutional timeout/retry/idempotency controls.
4. README is stale and still describes "Cloud Trader — Bootstrap Scaffold (v2)".

## Correct resume point
Do not redesign AEGIS from scratch.

Resume in this order:
1. Preserve local work.
2. Compare local worktree vs GitHub.
3. Recover latest State->Trigger backtest.
4. Consolidate canonical architecture/governance files.
5. Fix policy enforcement and add negative-path tests.
6. Encode State and Trigger as first-class contracts.
7. Continue Stage-1 dependency order.
8. Build canonical OMS before live execution.

## Continuity standard
Every engineering session must end with a durable handoff recording:

```text
PROJECT
DATE/TIME
REPOSITORY
BRANCH
HEAD COMMIT
LOCAL DIRTY STATUS
FILES MODIFIED
LAST SUCCESSFUL TEST
LAST FAILED TEST
CURRENT ARCHITECTURE STEP
DECISIONS MADE
OPEN DEFECTS
EXACT NEXT ACTION
RESTART COMMANDS
```

No architectural decision should exist only in chat. No completed/tested implementation should remain uncommitted across session boundaries.

## Recovery conclusion
AEGIS was not lost. The mission, architecture, blueprint, E*TRADE foundation, strategy abstraction, paper execution layer, data-pipeline work, Stage-1 order, major governance principles, exact recovered Constitution rules and State->Trigger correction all survived.

The principal remaining unknowns are:
1. complete exact wording of all 150 Constitution rules,
2. latest State->Trigger backtest implementation,
3. uncommitted local work after July 26, 2026,
4. exact final backup-script/handoff output,
5. later test outputs not committed or persisted.

**Immediate next action: inspect and preserve `C:\Users\garre\cloud-trader` before changing the local repository.**
