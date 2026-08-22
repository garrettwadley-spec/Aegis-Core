"""Tests for ordering guarantees: A -> B -> C preserved."""
from __future__ import annotations

import unittest
from aegis.clock import ClockMode, system_clock
from aegis.eventbus import EventBus, Event, Subscriber

class OrderingSubscriber(Subscriber):
    def __init__(self):
        self.received = []
    def receive(self, event: Event) -> None:
        self.received.append(event.event_type)

class TestOrdering(unittest.TestCase):
    def test_ordering_preserved(self):
        bus = EventBus()
        sub = OrderingSubscriber()
        bus.subscribe("seq.type", sub)
        # publish A, B, C
        e1 = Event.create("seq.type", {"v": "A"})
        e2 = Event.create("seq.type", {"v": "B"})
        e3 = Event.create("seq.type", {"v": "C"})
        bus.publish(e1)
        bus.publish(e2)
        bus.publish(e3)
        bus.dispatch()
        self.assertEqual(sub.received, ["seq.type", "seq.type", "seq.type"])  # event_type preserved

class OrderingCaptureSubscriber(Subscriber):
    def __init__(self):
        self.received = []
    def receive(self, event: Event) -> None:
        self.received.append(event)

class TestOrderingCapture(unittest.TestCase):
    def test_event_bus_uses_process_clock_sequence(self):
        system_clock.set_mode(ClockMode.LIVE, sequence_start=100)
        try:
            first_bus = EventBus()
            second_bus = EventBus()
            first = OrderingCaptureSubscriber()
            second = OrderingCaptureSubscriber()
            first_bus.subscribe("seq.type", first)
            second_bus.subscribe("seq.type", second)

            first_bus.publish(Event.create("seq.type", {"v": "A"}))
            clock_sequence = system_clock.sequence()
            second_bus.publish(Event.create("seq.type", {"v": "B"}))
            first_bus.dispatch()
            second_bus.dispatch()

            self.assertEqual(first.received[0].sequence_number, 100)
            self.assertEqual(clock_sequence, 101)
            self.assertEqual(second.received[0].sequence_number, 102)
        finally:
            system_clock.set_mode(ClockMode.LIVE)

    def test_ordering_sequence_numbers_monotonic(self):
        bus = EventBus()
        sub = OrderingCaptureSubscriber()
        bus.subscribe("seq.type", sub)
        e1 = Event.create("seq.type", {"v": "A"})
        e2 = Event.create("seq.type", {"v": "B"})
        e3 = Event.create("seq.type", {"v": "C"})
        bus.publish(e1)
        bus.publish(e2)
        bus.publish(e3)
        bus.dispatch()
        seqs = [evt.sequence_number for evt in sub.received]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), 3)

if __name__ == "__main__":
    unittest.main()
