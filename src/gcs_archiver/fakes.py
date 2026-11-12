"""An in-memory stand-in for GCS + Storage Transfer Service, used by tests and `gcs-archiver demo`."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from .models import ObjectInfo
from .storage import InMemoryBackend


class FakeTransferClient:
    """Executes a job synchronously against an InMemoryBackend, honouring the same conditions STS does."""

    def __init__(self, storage: InMemoryBackend, target_class: str = "ARCHIVE", fail_prefixes: set[str] | None = None):
        self.storage = storage
        self.target_class = target_class
        self.fail_prefixes = fail_prefixes or set()
        self.jobs: dict[str, str] = {}

    def create_job(self, spec: dict) -> str:
        ts = spec["transferSpec"]
        cond = ts["objectConditions"]
        prefixes = cond.get("includePrefixes", [""])
        min_age = timedelta(seconds=int(cond["minTimeElapsedSinceLastModification"].rstrip("s")))
        cutoff = datetime.now(UTC) - min_age
        name = f"transferJobs/{len(self.jobs) + 1}"
        if any(p in self.fail_prefixes for p in prefixes):
            self.jobs[name] = "FAILED"
            return name
        src, dst = ts["gcsDataSource"]["bucketName"], ts["gcsDataSink"]["bucketName"]
        names = [o.name for p in prefixes for o in self.storage.list_objects(src, p) if o.updated < cutoff]
        self.storage.copy(src, dst, names, self.target_class, ts["transferOptions"]["deleteObjectsFromSourceAfterTransfer"])
        self.jobs[name] = "SUCCESS"
        return name

    def job_status(self, job_name: str) -> str:
        return self.jobs[job_name]


def sample_bucket(seed: int = 7, now: datetime | None = None) -> list[ObjectInfo]:
    """A realistic-looking ledger export layout: tables/<name>/dt=YYYY-MM-DD/part-N.parquet."""
    rng = random.Random(seed)
    now = now or datetime.now(UTC)
    objects = []
    for table in ("journal_lines", "postings", "reconciliation"):
        for days_ago in range(0, 900, 7):
            day = now - timedelta(days=days_ago)
            for part in range(rng.randint(1, 3)):
                size = rng.randint(200, 900) * 1024**2
                cls = "STANDARD" if days_ago < 30 else "NEARLINE" if days_ago < 365 else "COLDLINE"
                objects.append(ObjectInfo(f"tables/{table}/dt={day:%Y-%m-%d}/part-{part}.parquet", size, day, cls))
    return objects
