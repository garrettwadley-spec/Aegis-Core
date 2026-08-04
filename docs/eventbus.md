"""Documentation for the Event Bus."""

# Event Bus

## Purpose

The Aegis Event Bus provides a deterministic, in-process publish/subscribe
mechanism intended as the foundational messaging primitive for Aegis v1.0.

## Architecture

- Immutable Event objects (dataclass, frozen).
- Deterministic ordering guaranteed by a monotonic sequence number and FIFO
enqueue/dequeue semantics.
- Synchronous delivery to subscribers during dispatch; no background threads
or external brokers are required.

## Public API

- EventBus.publish(event) -> Receipt
- EventBus.subscribe(event_type, subscriber) -> Subscription
- EventBus.unsubscribe(subscription) -> bool
- EventBus.dispatch() -> List[Receipt]

Types:
- Event: Immutable event object with metadata (event_id, sequence_number, trace/correlation ids).
- Subscriber: Abstract interface with receive(event) method.
- Receipt: Acknowledgement of publish/dispatch operations.

## Example usage

```python
from aegis.eventbus import EventBus, Event, Subscriber

class PrintSubscriber(Subscriber):
    def receive(self, event: Event) -> None:
        print("received", event.event_type, event.sequence_number)

bus = EventBus()
sub = bus.subscribe("order.created", PrintSubscriber())
e = Event.create("order.created", {"order_id": 123})
receipt = bus.publish(e)
bus.dispatch()
```

## Thread safety assumptions

- The EventBus uses a simple Lock to protect internal state. Concurrent
publish/subscribe operations are safe; dispatch executes synchronously and
will block during delivery.

## Future extensions

- Asynchronous dispatch/backpressure strategies.
- Pluggable persistence for event replay.
- Integration adapters for external brokers.
