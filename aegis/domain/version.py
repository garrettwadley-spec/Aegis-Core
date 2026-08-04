"""Version helper for domain objects."""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class Version:
    """Represents an immutable version number for domain objects."""
    version: int = 1
