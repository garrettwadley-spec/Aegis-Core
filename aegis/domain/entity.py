"""Entity base class.

Entities are identity-based objects. Equality and hashing are determined by
object identity (object_id).
"""
from __future__ import annotations

from dataclasses import dataclass
from .base import DomainObject

@dataclass(frozen=True)
class Entity(DomainObject):
    """Entity foundation: identity-based equality."""

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, Entity):
            return False
        return self.object_id == other.object_id

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(self.object_id)
