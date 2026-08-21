# Capability C002 Manifest

Capability ID: C002

Architecture Version: Aegis v1.0

Mission: Implement authoritative Clock Service for Aegis.

Files:
- aegis/clock/__init__.py
- aegis/clock/clock.py
- aegis/clock/mode.py
- aegis/clock/sequence.py
- aegis/clock/timestamp.py
- aegis/clock/utc.py
- aegis/clock/monotonic.py
- aegis/clock/interfaces.py
- tests/clock/test_clock.py
- tests/clock/test_sequence.py
- tests/clock/test_monotonic.py
- tests/clock/test_modes.py
- docs/clock_service.md
- engineering/capability_C002_manifest.md

Dependencies: None (Python standard library only). Python 3.11+

Definition of Done:
- Branch created: mission-002-clock-service
- All files present and importable
- Unit tests cover UTC, monotonic, sequence, modes, and replay behavior
- No placeholders, TODOs, or stubs
- Commit message: feat(clock): implement deterministic Clock Service foundation

SELF REVIEW

Architecture Rules Satisfied
22
23
24
110
126
132
145
149

Known Deviations
- Public enforcement of "no subsystem may call system time" remains organizational: code centralizes access but cannot technically prevent calls to system time functions.

Known Risks
- Sequence numbers are process-local and not persisted across restarts; cross-process sequencing requires coordination.
- Simulated monotonic values are derived from a base and call counts; misconfiguration could yield non-progressing monotonic values if replay_step_seconds is 0.

Implementation Decisions
- SequenceGenerator accepts an explicit "seed" parameter. If seed is provided, the first returned sequence equals the seed (internal counter initialized to seed-1). If seed is None, sequences start at 1.
- Naive datetime inputs are treated as UTC and normalized via ensure_utc.

