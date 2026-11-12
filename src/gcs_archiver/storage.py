"""Storage backends. The GCS backend is imported lazily so the planner and tests run without GCP libraries."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Protocol

from .models import ObjectInfo


class StorageBackend(Protocol):
    def list_objects(self, bucket: str, prefix: str = "") -> Iterator[ObjectInfo]: ...


class GcsBackend:
    def __init__(self, project_id: str) -> None:
        from google.cloud import storage  # optional dependency

        self._client = storage.Client(project=project_id)

    def list_objects(self, bucket: str, prefix: str = "") -> Iterator[ObjectInfo]:
        for blob in self._client.list_blobs(bucket, prefix=prefix or None):
            if blob.name.endswith("/"):
                continue  # folder placeholder objects
            yield ObjectInfo(blob.name, blob.size or 0, blob.updated, blob.storage_class or "STANDARD")


class InMemoryBackend:
    """Used by tests and `--demo` runs."""

    def __init__(self, buckets: dict[str, Iterable[ObjectInfo]] | None = None) -> None:
        self.buckets: dict[str, dict[str, ObjectInfo]] = {
            b: {o.name: o for o in objs} for b, objs in (buckets or {}).items()
        }

    def list_objects(self, bucket: str, prefix: str = "") -> Iterator[ObjectInfo]:
        for name in sorted(self.buckets.get(bucket, {})):
            if name.startswith(prefix):
                yield self.buckets[bucket][name]

    def copy(self, src: str, dst: str, names: Iterable[str], storage_class: str, delete_source: bool) -> None:
        dest = self.buckets.setdefault(dst, {})
        for name in names:
            o = self.buckets[src][name]
            dest[name] = ObjectInfo(o.name, o.size, o.updated, storage_class)
            if delete_source:
                del self.buckets[src][name]
