"""Documentation for the Clock Service."""

# Clock Service

## Purpose

The Aegis Clock Service centralizes all time and sequence concerns for the
Aegis architecture. It is the single authority for UTC timestamps, monotonic
timestamps, sequence numbers, and runtime clock mode.

## Architecture

- Single Clock class provides the public API.
- SequenceGenerator owns global sequence numbers.
- Modes allow deterministic control for replay/backtest/simulation.

## Public API

- Clock.now() -> datetime
- Clock.monotonic() -> float
- Clock.sequence() -> int
- Clock.mode() -> ClockMode
- Clock.set_mode(mode, **kwargs) -> None

## Clock Modes

LIVE - Real system time
PAPER, BACKTEST, SIMULATION - Deterministic simulated modes
REPLAY - Deterministic replay mode with configurable start and step

## Sequence Generation

SequenceGenerator provides global monotonic integers starting at 1 and
managed exclusively by Clock.sequence().

## Deterministic Replay

Replay mode can be configured via set_mode with replay_start_time and
replay_step_seconds to produce repeatable timelines.

## Engineering Notes

No subsystem should call system time functions (datetime.now, time.time,
perf_counter, or time.monotonic) directly after migration. All requests
should be routed through the Clock service.
