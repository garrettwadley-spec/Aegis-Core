import os, json, yaml, time
from pathlib import Path
from typing import Dict, Any, Optional, List
import uuid
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

# -----------------------------
# Paths / config
# -----------------------------
ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "policy.yaml"
INDEX_PATH = ROOT / "rag" / "index.json"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_ID = os.getenv("AEGIS_MODEL", "llama3.1:8b-instruct")

def load_policy() -> Dict[str, Any]:
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_index() -> Dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {"items": []}

POLICY = load_policy()
INDEX = load_index()

# -----------------------------
# Run registry (Multi-Run v0)
# -----------------------------
RUNS_DIR = ROOT / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

RUN_REGISTRY: Dict[str, Dict[str, Any]] = {}

# -----------------------------
# Tools
# -----------------------------
from aegis.tools.data_fetch import data_fetch
from aegis.tools.backtest_run import backtest_run
from aegis.tools.train_run import train_run
from aegis.tools.risk_simulate import risk_simulate

TOOLS = {
    "data.fetch": data_fetch,
    "backtest.run": backtest_run,
    "train.run": train_run,
    "risk.simulate": risk_simulate,
}

def allowed_tool(name: str) -> bool:
    allow = POLICY.get("allowed_tools", [])
    deny = POLICY.get("denied_tools", [])

    if name in deny:
        return False

    if allow and name not in allow:
        return False

    return True

# -----------------------------
# API
# -----------------------------
app = FastAPI(title="Aegis Orchestrator", version="0.1.0")

class Ask(BaseModel):
    question: str

class MultiRunRequest(BaseModel):
    name: str
    symbols: List[str]
    strategies: List[str]
    timeframe: str
    start: Optional[str] = None
    end: Optional[str] = None

@app.get("/health")
def health():
    return {
        "status": "ok",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "ollama_url": OLLAMA_URL,
        "runs_dir": str(RUNS_DIR),
    }

@app.get("/runs")
def list_runs(limit: int = 50):
    items = []

    if not RUNS_DIR.exists():
        return {"count": 0, "items": []}

    paths = sorted(
        RUNS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for p in paths[: max(0, min(limit, 500))]:
        st = p.stat()

        items.append({
            "run_id": p.stem,
            "path": str(p),
            "size_bytes": st.st_size,
            "updated_at": datetime.fromtimestamp(
                st.st_mtime,
                tz=timezone.utc
            ).isoformat(),
        })

    return {"count": len(items), "items": items}

@app.get("/runs/{run_id}")
def get_run(run_id: str):

    p = RUNS_DIR / f"{run_id}.json"

    if not p.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Run not found: {run_id}"
        )

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read run artifact: {e}"
        )

    data["_file"] = {
        "path": str(p),
        "size_bytes": p.stat().st_size,
        "updated_at": datetime.fromtimestamp(
            p.stat().st_mtime,
            tz=timezone.utc
        ).isoformat(),
    }

    return data

@app.post("/ask")
def ask(req: Ask):
    return {
        "answer": "Ask endpoint operational. Use explicit tool calls or /multi-run."
    }

def _write_run_artifact(run_id: str, payload: Dict[str, Any]) -> str:
    path = RUNS_DIR / f"{run_id}.json"

    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8"
    )

    return str(path)

def _multi_run_job(run_id: str, req: MultiRunRequest):

    results = []

    for strategy in req.strategies:
        for symbol in req.symbols:

            if not allowed_tool("backtest.run"):
                raise HTTPException(
                    status_code=403,
                    detail="Tool not allowed by policy: backtest.run"
                )

            output = backtest_run(
                strategy=strategy,
                symbols=[symbol],
                params=None
            )

            results.append({
                "strategy": strategy,
                "symbol": symbol,
                "output": output,
            })

    artifact_payload = {
        "run_id": run_id,
        "status": "COMPLETE",
        "request": req.dict(),
        "results": results,
    }

    artifact = _write_run_artifact(run_id, artifact_payload)

    RUN_REGISTRY[run_id]["status"] = "COMPLETE"
    RUN_REGISTRY[run_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    RUN_REGISTRY[run_id]["artifact"] = artifact

@app.post("/multi-run")
def start_multi_run(req: MultiRunRequest, background: BackgroundTasks):

    run_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    RUN_REGISTRY[run_id] = {
        "run_id": run_id,
        "status": "QUEUED",
        "created_at": now,
        "updated_at": now,
        "request": req.dict(),
        "artifact": None,
    }

    background.add_task(_multi_run_job, run_id, req)

    return {
        "run_id": run_id,
        "status": "QUEUED",
        "created_at": now
    }

@app.get("/multi-run/{run_id}")
def get_multi_run(run_id: str):

    if run_id not in RUN_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail="run_id not found"
        )

    return RUN_REGISTRY[run_id]