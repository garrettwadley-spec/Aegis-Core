"""Base domain object definitions.

Defines DomainObject which provides common fields and serialization support.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional
import uuid

from .identity import Identity
from .version import Version
from .trace import TraceContext
from .correlation import CorrelationContext
from .metadata import Metadata
from .timestamp import Timestamp
from aegis.clock import system_clock
from aegis.clock.utc import ensure_utc


@dataclass(frozen=True)
class DomainObject:
    """Immutable foundational domain object.

    Attributes:
        object_id: Unique identifier for the object (string UUID).
        version: Version information for the object.
        created_at: Time of creation (timezone-aware UTC).
        trace_id: Trace identifier for distributed tracing.
        correlation_id: Correlation identifier for grouping related objects.
        metadata: Read-only mapping for arbitrary metadata.
    """

    object_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = field(default=1)
    created_at: datetime = field(default_factory=lambda: system_clock.now())
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _metadata: Optional[Mapping[str, Any]] = field(default=None, repr=False)

    def __post_init__(self) -> None:  # type: ignore[override]
        # Normalize created_at to timezone-aware UTC and freeze metadata
        ca = system_clock.now() if self.created_at is None else ensure_utc(self.created_at)
        meta = self._metadata or {}
        if not isinstance(meta, Mapping):
            meta = dict(meta)
        frozen = MappingProxyType(dict(meta))
        object.__setattr__(self, "created_at", ca)
        object.__setattr__(self, "_metadata", frozen)

    @property
    def metadata(self) -> Mapping[str, Any]:
        """Return read-only metadata mapping."""
        return self._metadata or MappingProxyType({})

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the DomainObject to a JSON-serializable dict."""
        return {
            "object_id": self.object_id,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainObject":
        """Deserialize a DomainObject from a dict produced by to_dict.

        Note: created_at must be an ISO 8601 string.
        """
        ca = data.get("created_at")
        if isinstance(ca, str):
            created_at = datetime.fromisoformat(ca)
        else:
            created_at = None
        return cls(
            object_id=data.get("object_id", str(uuid.uuid4())),
            version=int(data.get("version", 1)),
            created_at=created_at,
            trace_id=data.get("trace_id", str(uuid.uuid4())),
            correlation_id=data.get("correlation_id", str(uuid.uuid4())),
            _metadata=data.get("metadata", {}),
        )
