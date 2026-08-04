"""Tests validating Clock.now, monotonic, and basic behaviors."""
from __future__ import annotations

import unittest
from time import sleep
from aegis.clock import Clock, ClockMode

class TestClockNow(unittest.TestCase):
    def test_utc_timestamps_increase(self):
        clock = Clock()
        t1 = clock.now()
        t2 = clock.now()
        self.assertLessEqual(t1, t2)

    def test_modes_transition(self):
        clock = Clock()
        self.assertEqual(clock.mode(), ClockMode.LIVE)
        clock.set_mode(ClockMode.REPLAY, replay_start_time="2026-01-01T00:00:00+00:00", replay_step_seconds=1.0, sequence_start=100)
        self.assertEqual(clock.mode(), ClockMode.REPLAY)

if __name__ == "__main__":
    unittest.main()
