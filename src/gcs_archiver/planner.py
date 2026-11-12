"""Decides what to archive and how to split it into transfer jobs."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from .models import Batch, ObjectInfo


def cutoff_for(min_age_days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=min_age_days)


def eligible(objects: Iterable[ObjectInfo], cutoff: datetime, target_class: str) -> list[ObjectInfo]:
    """Objects last modified before the cutoff that are not already in the target class."""
    return [o for o in objects if o.updated < cutoff and o.storage_class != target_class]


def batch_prefix(name: str, depth: int) -> str:
    parts = name.split("/")[:-1]  # drop the file name
    return "/".join(parts[:depth]) + "/" if depth and parts else ""


def plan_batches(objects: Iterable[ObjectInfo], depth: int, max_objects: int, max_bytes: int) -> list[Batch]:
    """Groups objects by prefix (one job per folder at `depth`), splitting groups that exceed the limits.

    Jobs scoped to a prefix keep failures small and retries cheap: a failed job only touches its own folder.
    """
    groups: dict[str, list[ObjectInfo]] = defaultdict(list)
    for o in objects:
        groups[batch_prefix(o.name, depth)].append(o)

    batches: list[Batch] = []
    for prefix in sorted(groups):
        current = Batch(prefix)
        for o in sorted(groups[prefix], key=lambda x: x.name):
            if current.objects and (
                current.object_count >= max_objects or current.total_bytes + o.size > max_bytes
            ):
                batches.append(current)
                current = Batch(prefix)
            current.objects.append(o)
        batches.append(current)
    return batches


def summarize(batches: list[Batch]) -> dict[str, int]:
    by_class: dict[str, int] = defaultdict(int)
    for b in batches:
        for o in b.objects:
            by_class[o.storage_class] += o.size
    return dict(by_class)
