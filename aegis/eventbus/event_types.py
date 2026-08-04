"""Event type definitions.

Simple alias for readability; using str for flexibility.
"""
from typing import NewType

EventType = NewType("EventType", str)
