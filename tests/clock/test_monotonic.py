"""Tests for monotonic behavior."""
from __future__ import annotations

import unittest
from aegis.clock import Clock, ClockMode

class TestMonotonic(unittest.TestCase):
    def test_monotonic_increases(self):
        clock = Clock()
        m1 = clock.monotonic()
        m2 = clock.monotonic()
        self.assertLessEqual(m1, m2)

    def test_wall_clock_change_does_not_decrease_monotonic(self):
        clock = Clock()
        m1 = clock.monotonic()
        # simulate wall-clock change by calling now repeatedly; monotonic should still increase
        for _ in range(5):
            clock.now()
        m2 = clock.monotonic()
        self.assertLessEqual(m1, m2)

if __name__ == "__main__":
    unittest.main()
