"""Clock modes for the Aegis Clock Service."""
from __future__ import annotations

from enum import Enum

class ClockMode(str, Enum):
    """Supported runtime clock modes for Aegis.

    LIVE: Use real system time and monotonic.
    PAPER: Lightweight simulated environment for paper trading.
    BACKTEST: Backtest mode (deterministic timeline driven by dataset).
    SIMULATION: Simulation mode (time advances under control).
    REPLAY: Replay mode (deterministic, repeatable timeline).
    """
    LIVE = "LIVE"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"
    SIMULATION = "SIMULATION"
    REPLAY = "REPLAY"
