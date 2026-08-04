"""Identity helper for domain objects."""
from __future__ import annotations

from dataclasses import dataclass
import uuid

@dataclass(frozen=True)
class Identity:
    """Lightweight identity wrapper.

    Wraps a string UUID to provide a single canonical identity type for
    domain objects. Using a dedicated type improves readability and allows
    future extension.
    """
    id: str

    @classmethod
    def new(cls) -> "Identity":
        """Create a new Identity with a generated UUID."""
        return cls(id=str(uuid.uuid4()))

    @classmethod
    def from_str(cls, value: str) -> "Identity":
        """Create an Identity from an existing UUID string."""
        return cls(id=value)
