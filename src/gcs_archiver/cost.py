from __future__ import annotations

from dataclasses import dataclass

GB = 1024**3


@dataclass(frozen=True)
class CostEstimate:
    bytes_moved: int
    current_monthly_usd: float
    archived_monthly_usd: float

    @property
    def monthly_savings_usd(self) -> float:
        return self.current_monthly_usd - self.archived_monthly_usd

    @property
    def annual_savings_usd(self) -> float:
        return 12 * self.monthly_savings_usd


def estimate(bytes_by_class: dict[str, int], target_class: str, prices: dict[str, float]) -> CostEstimate:
    """Storage-only estimate. It ignores retrieval and early-deletion fees, which matter if archived data is read."""
    current = sum(b / GB * prices.get(cls, prices["STANDARD"]) for cls, b in bytes_by_class.items())
    total = sum(bytes_by_class.values())
    return CostEstimate(total, current, total / GB * prices[target_class])


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024 or unit == "PB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    raise AssertionError("unreachable")
