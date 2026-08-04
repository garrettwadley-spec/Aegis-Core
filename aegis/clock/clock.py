"""Authoritative Clock Service for Aegis.

This module centralizes all access to wall-clock UTC timestamps, monotonic
timestamps, sequence numbers, and runtime clock mode. No other subsystem
should call system time functions directly once migrated.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import time
from threading import Lock
from typing import Any, Dict, Optional

from .mode import ClockMode
from .sequence import SequenceGenerator
from .utc import ensure_utc, utc_now
from .monotonic import system_monotonic


class Clock:
    """Authoritative Clock Service for Aegis.

    Public API:
        now() -> datetime
        monotonic() -> float
        sequence() -> int
        mode() -> ClockMode
        set_mode(mode: ClockMode, **kwargs) -> None

    Modes may accept additional parameters via set_mode kwargs for deterministic
    control (e.g., replay_start_time, replay_step_seconds, sequence_start).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._mode: ClockMode = ClockMode.LIVE
        # Sequence generator owns all sequence numbers; default starts at 1
        self._seq = SequenceGenerator()
        # Monotonic base captured at init to produce monotonic times
        self._monotonic_base = system_monotonic()
        # Replay control
        self._replay_start_time: Optional[datetime] = None
        self._replay_step_seconds: float = 0.0
        self._replay_call_count: int = 0
        self._replay_sequence_start: int = 0

    def now(self) -> datetime:
        """Return an authoritative timezone-aware UTC datetime according to mode.

        In LIVE mode this returns the system UTC time. In REPLAY/SIMULATION/BACKTEST
        it returns a deterministic timeline controlled via set_mode kwargs.
        """
        if self.mode() == ClockMode.LIVE:
            return utc_now()

        if self.mode() == ClockMode.REPLAY:
            with self._lock:
                if self._replay_start_time is None:
                    # default to now if not configured
                    self._replay_start_time = utc_now()
                t = self._replay_start_time + timedelta(seconds=self._replay_step_seconds * self._replay_call_count)
                # increment call count deterministically
                self._replay_call_count += 1
                return ensure_utc(t)

        # For other simulated modes, default deterministic behavior: steady increment per call
        with self._lock:
            if self._replay_start_time is None:
                self._replay_start_time = utc_now()
            t = self._replay_start_time + timedelta(seconds=self._replay_step_seconds * self._replay_call_count)
            self._replay_call_count += 1
            return ensure_utc(t)

    def monotonic(self) -> float:
        """Return a monotonic timestamp.

        In LIVE mode this delegates to system_monotonic(). In replay/simulated
        modes it derives a monotonic value from a base plus deterministic steps.
        """
        if self.mode() == ClockMode.LIVE:
            return system_monotonic()

        with self._lock:
            # In replay, simulate monotonic as base + call_count*step
            delta = self._replay_call_count * max(1e-6, self._replay_step_seconds)
            return self._monotonic_base + delta

    def sequence(self) -> int:
        """Return the next global monotonic sequence number.

        The ClockService owns sequence generation; values never repeat or decrease.
        """
        return self._seq.next()

    def mode(self) -> ClockMode:
        """Return the current ClockMode."""
        return self._mode

    def set_mode(self, mode: ClockMode, **kwargs: Any) -> None:
        """Set the runtime clock mode and optional deterministic parameters.

        Supported kwargs for REPLAY/SIMULATION/BACKTEST/PAPER:
            replay_start_time: datetime | str | None -- starting UTC time
            replay_step_seconds: float -- seconds advanced per now() call
            sequence_start: int -- optional sequence generator start value
        """
        with self._lock:
            self._mode = mode
            # Configure replay parameters
            replay_start_time = kwargs.get("replay_start_time")
            if isinstance(replay_start_time, str):
                # parse ISO format
                try:
                    replay_start_time = datetime.fromisoformat(replay_start_time)
                except Exception:
                    replay_start_time = None
            if replay_start_time is not None:
                # ensure timezone-aware UTC
                self._replay_start_time = ensure_utc(replay_start_time)
            else:
                self._replay_start_time = None

            step = kwargs.get("replay_step_seconds")
            if isinstance(step, (int, float)):
                self._replay_step_seconds = float(step)
            else:
                # sensible default: 0.0 (stable time unless advanced manually)
                self._replay_step_seconds = 0.0

            seq_start = kwargs.get("sequence_start")
            if isinstance(seq_start, int) and seq_start >= 0:
                # re-seed sequence generator so that the first returned value equals seq_start
                self._seq = SequenceGenerator(seed=seq_start)
            # reset replay counters
            self._replay_call_count = 0

