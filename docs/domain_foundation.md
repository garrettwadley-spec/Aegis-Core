"""Documentation: Domain foundation."""

# Domain Foundation

## Purpose

Provide the immutable, versioned, traceable base classes that all future
business domain objects inherit. F003 contains only infrastructure — no
business entities — so the model is stable and reviewable.

## Architecture

- DomainObject is the canonical base class: object_id, version, timestamps,
  trace and correlation ids, and metadata.
- Entity extends DomainObject and defines identity-based equality.
- ValueObject extends DomainObject and uses structural equality.
- Serialization helpers provide to_dict/from_dict interfaces for round-trip.

## Inheritance model

DomainObject -> Entity / ValueObject -> BusinessObjects

## Example usage

```python
from aegis.domain import DomainObject, Entity

class MyEntity(Entity):
    pass

obj = DomainObject()
print(obj.to_dict())
```

## Notes

- All objects are dataclass(frozen=True) to guarantee immutability at the
  object level. Mutable payloads inside metadata should be avoided or
  provided as immutable structures.
