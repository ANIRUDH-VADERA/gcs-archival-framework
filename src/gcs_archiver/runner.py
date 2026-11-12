"""End-to-end flow: plan -> submit jobs -> poll -> verify. Every step is recorded in the ledger."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from . import planner
from .config import ArchiveConfig
from .cost import CostEstimate, estimate
from .ledger import Ledger
from .models import Batch
from .storage import StorageBackend
from .transfer import TransferClient, build_job_spec


@dataclass
class Plan:
    batches: list[Batch]
    cost: CostEstimate

    def numbered(self) -> list[tuple[Batch, int]]:
        """(batch, seq) pairs; seq separates batches that were split from the same prefix."""
        seen: dict[str, int] = defaultdict(int)
        out = []
        for b in self.batches:
            out.append((b, seen[b.key]))
            seen[b.key] += 1
        return out


def make_plan(cfg: ArchiveConfig, storage: StorageBackend, now: datetime | None = None) -> Plan:
    cutoff = planner.cutoff_for(cfg.min_age_days, now)
    objects = [o for p in cfg.prefixes for o in storage.list_objects(cfg.source_bucket, p)]
    chosen = planner.eligible(objects, cutoff, cfg.target_storage_class)
    batches = planner.plan_batches(chosen, cfg.batch_depth, cfg.max_objects_per_batch, cfg.max_bytes_per_batch)
    cost = estimate(planner.summarize(batches), cfg.target_storage_class, cfg.prices_per_gb_month)
    return Plan(batches, cost)


def submit(plan: Plan, cfg: ArchiveConfig, transfer: TransferClient, ledger: Ledger, limit: int | None = None) -> int:
    """Creates jobs for batches that have not succeeded yet. Safe to re-run after a failure."""
    submitted = 0
    for batch, seq in plan.numbered():
        if limit is not None and submitted >= limit:
            break
        if ledger.is_done(batch.key, seq):
            continue
        row = ledger.get(batch.key, seq)
        if row is not None and row["status"] in {"SUBMITTED", "IN_PROGRESS", "QUEUED"}:
            continue
        job_name = transfer.create_job(build_job_spec(batch, cfg))
        ledger.upsert(batch.key, seq, job_name=job_name, status="SUBMITTED",
                      object_count=batch.object_count, total_bytes=batch.total_bytes)
        submitted += 1
    return submitted


def refresh(transfer: TransferClient, ledger: Ledger) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in ledger.all():
        status = row["status"]
        if row["job_name"] and status not in {"SUCCESS", "VERIFIED", "FAILED", "MISMATCH"}:
            status = transfer.job_status(row["job_name"])
            ledger.upsert(row["batch_key"], row["seq"], status=status)
        counts[status] += 1
    return dict(counts)


def verify(plan: Plan, cfg: ArchiveConfig, storage: StorageBackend, ledger: Ledger) -> list[str]:
    """Checks every planned object exists in the archive bucket with the same size. Returns problems found."""
    problems = []
    for batch, seq in plan.numbered():
        row = ledger.get(batch.key, seq)
        if row is None or row["status"] != "SUCCESS":
            continue
        archived = {o.name: o.size for o in storage.list_objects(cfg.archive_bucket, batch.prefix)}
        missing = [o.name for o in batch.objects if archived.get(o.name) != o.size]
        if missing:
            problems.append(f"{batch.key}#{seq}: {len(missing)} objects missing or different, e.g. {missing[0]}")
            ledger.upsert(batch.key, seq, status="MISMATCH", note=f"{len(missing)} missing")
        else:
            ledger.upsert(batch.key, seq, status="VERIFIED", verified=1)
    return problems
