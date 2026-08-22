"""Unit tests for publish behavior."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from aegis.clock import system_clock
from aegis.eventbus import EventBus, Event

class TestPublish(unittest.TestCase):
    def test_event_timestamp_comes_from_clock(self):
        expected = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        with patch.object(system_clock, "now", return_value=expected) as clock_now:
            event = Event.create("test.timestamp", {})

        self.assertEqual(event.created_at, expected)
        clock_now.assert_called_once_with()

    def test_publish_returns_receipt(self):
        bus = EventBus()
        event = Event.create("test.publish", {"v": 1})
        receipt = bus.publish(event)
        self.assertEqual(receipt.event_id, event.event_id)
        self.assertEqual(receipt.delivery_status, "queued")
        self.assertIsInstance(receipt.subscriber_count, int)

if __name__ == "__main__":
    unittest.main()
