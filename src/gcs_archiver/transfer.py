"""Builds and submits Storage Transfer Service jobs, one per batch."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

from .config import ArchiveConfig
from .models import Batch


def build_job_spec(batch: Batch, cfg: ArchiveConfig, today: date | None = None) -> dict:
    """A one-time STS job that copies only this batch's prefix and only objects older than the age limit.

    The age condition is enforced again by the service itself (minTimeElapsedSinceLastModification),
    so an object modified between planning and execution is never moved.
    """
    run_day = today or datetime.now(timezone.utc).date()
    day = {"year": run_day.year, "month": run_day.month, "day": run_day.day}
    conditions: dict = {"minTimeElapsedSinceLastModification": f"{cfg.min_age_days * 86400}s"}
    if batch.prefix:
        conditions["includePrefixes"] = [batch.prefix]
    return {
        "projectId": cfg.project_id,
        "description": f"archive {cfg.source_bucket}/{batch.key} older than {cfg.min_age_days}d",
        "status": "ENABLED",
        "schedule": {"scheduleStartDate": day, "scheduleEndDate": day},
        "transferSpec": {
            "gcsDataSource": {"bucketName": cfg.source_bucket},
            "gcsDataSink": {"bucketName": cfg.archive_bucket},
            "objectConditions": conditions,
            "transferOptions": {
                "overwriteWhen": "DIFFERENT",
                "deleteObjectsFromSourceAfterTransfer": cfg.delete_source_after_transfer,
                "metadataOptions": {"storageClass": "STORAGE_CLASS_DESTINATION_BUCKET_DEFAULT"},
            },
        },
    }


class TransferClient(Protocol):
    def create_job(self, spec: dict) -> str: ...
    def job_status(self, job_name: str) -> str: ...


class StsTransferClient:
    """Thin wrapper over google-cloud-storage-transfer. Imported lazily."""

    def __init__(self, project_id: str) -> None:
        from google.cloud import storage_transfer  # noqa: PLC0415 - optional dependency

        self._st = storage_transfer
        self._project_id = project_id
        self._client = storage_transfer.StorageTransferServiceClient()

    def create_job(self, spec: dict) -> str:
        job = self._client.create_transfer_job({"transfer_job": spec})
        return job.name

    def job_status(self, job_name: str) -> str:
        filter_ = f'{{"projectId":"{self._project_id}","jobNames":["{job_name}"]}}'
        ops = list(self._client.list_transfer_operations({"name": "transferOperations", "filter": filter_}))
        if not ops:
            return "QUEUED"
        # Operation metadata is a packed TransferOperation message.
        latest = self._st.TransferOperation.deserialize(ops[-1].metadata.value)
        return latest.status.name
