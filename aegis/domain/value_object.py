"""Value object base class.

ValueObjects are immutable and compared by their value (default dataclass
behavior).
"""
from __future__ import annotations

from dataclasses import dataclass
from .base import DomainObject

@dataclass(frozen=True)
class ValueObject(DomainObject):
    """ValueObject foundation: structural equality (dataclass default)."""

    # No changes; dataclass provided structural equality is appropriate.
    pass
