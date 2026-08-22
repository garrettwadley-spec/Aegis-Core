"""Aegis Clock package initialization."""

from .clock import Clock
from .mode import ClockMode
from .interfaces import ClockInterface

system_clock = Clock()

__all__ = ["Clock", "ClockMode", "ClockInterface", "system_clock"]
