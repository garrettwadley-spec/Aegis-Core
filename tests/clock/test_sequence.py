"""Tests for sequence generation guarantees."""
from __future__ import annotations

import unittest
from aegis.clock import Clock

class TestSequence(unittest.TestCase):
    def test_sequence_monotonic_unique(self):
        clock = Clock()
        seqs = [clock.sequence() for _ in range(10)]
        self.assertEqual(len(set(seqs)), len(seqs))
        self.assertEqual(seqs, sorted(seqs))

if __name__ == "__main__":
    unittest.main()
