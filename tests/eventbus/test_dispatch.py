"""Tests for dispatching semantics and unknown event types."""
from __future__ import annotations

import unittest
from aegis.domain import DomainObject
from aegis.eventbus import EventBus, Event, Subscriber

class PassthroughSubscriber(Subscriber):
    def __init__(self):
        self.received = []
    def receive(self, event: Event) -> None:
        self.received.append(event)

class TestDispatch(unittest.TestCase):
    def test_domain_object_payload_is_preserved(self):
        bus = EventBus()
        subscriber = PassthroughSubscriber()
        payload = DomainObject()
        bus.subscribe("domain.payload", subscriber)

        bus.publish(Event.create("domain.payload", payload))
        bus.dispatch()

        self.assertIs(subscriber.received[0].payload, payload)

    def test_mutable_payload_is_not_mutated(self):
        bus = EventBus()
        subscriber = PassthroughSubscriber()
        payload = {"items": ["A", "B"]}
        bus.subscribe("mutable.payload", subscriber)

        bus.publish(Event.create("mutable.payload", payload))
        bus.dispatch()

        self.assertEqual(payload, {"items": ["A", "B"]})
        self.assertIs(subscriber.received[0].payload, payload)

    def test_unknown_event_types_do_not_fail(self):
        bus = EventBus()
        # no subscribers for this type
        e = Event.create("unknown.type", {"a": 1})
        r = bus.publish(e)
        receipts = bus.dispatch()
        # dispatch should succeed with no receipts (no deliveries)
        self.assertIsInstance(receipts, list)

    def test_multiple_subscribers_receive_identical_event(self):
        bus = EventBus()
        a = PassthroughSubscriber()
        b = PassthroughSubscriber()
        bus.subscribe("multi.type", a)
        bus.subscribe("multi.type", b)
        e = Event.create("multi.type", {"k": "v"})
        bus.publish(e)
        bus.dispatch()
        self.assertEqual(len(a.received), 1)
        self.assertEqual(len(b.received), 1)
        # ensure they received events with same event_id and sequence_number
        self.assertEqual(a.received[0].event_id, b.received[0].event_id)
        self.assertEqual(a.received[0].sequence_number, b.received[0].sequence_number)

if __name__ == "__main__":
    unittest.main()
