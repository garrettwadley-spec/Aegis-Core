# Offline Paper Execution

LAUNCH-005 converts an existing actionable `MarketSignal` into a one-share
`TradeRequest` forced to `PAPER`, validates it with a minimal launch safety gate,
and routes it through the existing `ExecutionEngine` and `OrderRouter` using an
offline `BrokerProtocol` implementation.

`OfflinePaperBroker` fills deterministically at the matching canonical current
`MarketData.last` price. It has no credentials, network imports, commissions,
slippage, portfolio sizing, or live-order capability.

Every attempted paper decision is appended to
`runs/decisions/decisions.jsonl`. Runtime records are ignored by Git. Records
explicitly identify configured replay factors and must not be interpreted as
evidence of live or fully market-derived strategy performance.

## Local Demo

```powershell
C:\Users\garre\Aegis-worktrees\foundation-integration-v1.venv\Scripts\python.exe -m scripts.run_first_paper_decision
```

Commissions, slippage, portfolio controls, richer risk policy, and real broker
connectivity remain future work.
