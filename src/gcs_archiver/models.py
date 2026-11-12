from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ObjectInfo:
    name: str
    size: int
    updated: datetime
    storage_class: str = "STANDARD"


@dataclass
class Batch:
    """A set of objects under one prefix that becomes a single transfer job."""

    prefix: str
    objects: list[ObjectInfo] = field(default_factory=list)

    @property
    def object_count(self) -> int:
        return len(self.objects)

    @property
    def total_bytes(self) -> int:
        return sum(o.size for o in self.objects)

    @property
    def key(self) -> str:
        return self.prefix or "<root>"
