"""Serialization helpers for domain objects."""
from __future__ import annotations

from typing import Any, Dict, Type
from .base import DomainObject


def to_dict(obj: DomainObject) -> Dict[str, Any]:
    """Convenience wrapper for DomainObject.to_dict."""
    return obj.to_dict()


def from_dict(data: Dict[str, Any]) -> DomainObject:
    """Deserialize into a DomainObject. For the base foundation this returns
    a DomainObject instance. Business objects should override this behavior
    and provide specific deserialization.
    """
    return DomainObject.from_dict(data)
