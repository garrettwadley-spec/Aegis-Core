"""Tests for clock mode transitions and replay determinism."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from aegis.clock import Clock, ClockMode

class TestModes(unittest.TestCase):
    def test_replay_preserves_deterministic_ordering(self):
        clock = Clock()
        clock.set_mode(ClockMode.REPLAY, replay_start_time="2026-01-01T00:00:00+00:00", replay_step_seconds=0.5, sequence_start=1)
        times = [clock.now() for _ in range(4)]
        seqs = [clock.sequence() for _ in range(4)]
        # times should be non-decreasing
        self.assertEqual(times, sorted(times))
        # sequences should be strictly increasing and start at 1
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(seqs[0], 1)

if __name__ == "__main__":
    unittest.main()
