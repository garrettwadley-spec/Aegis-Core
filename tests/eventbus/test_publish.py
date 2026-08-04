"""Unit tests for publish behavior."""
from __future__ import annotations

import unittest
from aegis.eventbus import EventBus, Event

class TestPublish(unittest.TestCase):
    def test_publish_returns_receipt(self):
        bus = EventBus()
        event = Event.create("test.publish", {"v": 1})
        receipt = bus.publish(event)
        self.assertEqual(receipt.event_id, event.event_id)
        self.assertEqual(receipt.delivery_status, "queued")
        self.assertIsInstance(receipt.subscriber_count, int)

if __name__ == "__main__":
    unittest.main()
