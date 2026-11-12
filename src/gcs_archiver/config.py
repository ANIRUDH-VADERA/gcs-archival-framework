from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Rough list prices in USD per GB-month for a single region. Override them in the config for your region.
DEFAULT_PRICES = {"STANDARD": 0.020, "NEARLINE": 0.010, "COLDLINE": 0.004, "ARCHIVE": 0.0012}


@dataclass
class ArchiveConfig:
    project_id: str
    source_bucket: str
    archive_bucket: str
    prefixes: list[str] = field(default_factory=lambda: [""])
    min_age_days: int = 395
    batch_depth: int = 1
    max_objects_per_batch: int = 1_000_000
    max_bytes_per_batch: int = 5 * 1024**4
    delete_source_after_transfer: bool = False
    target_storage_class: str = "ARCHIVE"
    prices_per_gb_month: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PRICES))
    ledger_path: str = "archive-ledger.sqlite"

    def __post_init__(self) -> None:
        if self.min_age_days < 30:
            raise ValueError("min_age_days below 30 is almost always a mistake for archival")
        if self.source_bucket == self.archive_bucket:
            raise ValueError("source and archive buckets must differ")
        if self.batch_depth < 0:
            raise ValueError("batch_depth must be >= 0")
        if self.target_storage_class not in self.prices_per_gb_month:
            raise ValueError(f"no price configured for {self.target_storage_class}")


def load_config(path: str | Path) -> ArchiveConfig:
    data = tomllib.loads(Path(path).read_text())
    prices = {**DEFAULT_PRICES, **data.pop("prices_per_gb_month", {})}
    return ArchiveConfig(**data, prices_per_gb_month=prices)
