"""Domain foundation package for Aegis.

This package provides the immutable, versioned, traceable base classes that
all future domain objects must inherit. It intentionally contains no
business-specific entities.
"""

from .base import DomainObject
from .entity import Entity
from .value_object import ValueObject
from .identity import Identity
from .version import Version
from .trace import TraceContext
from .correlation import CorrelationContext
from .metadata import Metadata
from .timestamp import Timestamp
from .serialization import to_dict, from_dict

__all__ = [
    "DomainObject",
    "Entity",
    "ValueObject",
    "Identity",
    "Version",
    "TraceContext",
    "CorrelationContext",
    "Metadata",
    "Timestamp",
    "to_dict",
    "from_dict",
]
