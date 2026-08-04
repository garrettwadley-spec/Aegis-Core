"""Unit tests for subscribe/receive behavior."""
from __future__ import annotations

import unittest
from aegis.eventbus import EventBus, Event, Subscriber

class RecordingSubscriber(Subscriber):
    def __init__(self):
        self.received = []
    def receive(self, event: Event) -> None:
        self.received.append(event)

class TestSubscribe(unittest.TestCase):
    def test_subscriber_receives_event(self):
        bus = EventBus()
        rec = RecordingSubscriber()
        bus.subscribe("test.receive", rec)
        event = Event.create("test.receive", {"x": True})
        bus.publish(event)
        bus.dispatch()
        self.assertEqual(len(rec.received), 1)
        self.assertEqual(rec.received[0].event_id, event.event_id)

if __name__ == "__main__":
    unittest.main()
