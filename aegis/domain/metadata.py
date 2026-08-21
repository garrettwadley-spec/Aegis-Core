"""Metadata helpers for domain objects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class Metadata:
    """Strongly-typed metadata container.

    Stored as an immutable mapping in DomainObject via MappingProxyType.
    """
    data: Mapping[str, Any]
