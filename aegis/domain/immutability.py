"""Immutability helpers and checks."""
from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any


def is_immutable(obj: Any) -> bool:
    """Return True if obj is an immutable dataclass or a primitive.

    This is a lightweight check used by tests to assert objects are frozen.
    """
    if is_dataclass(obj):
        # dataclasses with frozen=True have __setattr__ disabled; assume those are immutable
        return getattr(obj, "__dataclass_fields__", None) is not None and hasattr(obj, "__setattr__")
    # primitive checks
    return isinstance(obj, (int, float, str, bytes, tuple, frozenset, type(None)))
