"""Shared extraction results.

Extractor implementations stay in their own modules so the notebook can
walk through one idea at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    """What one extractor invocation actually did."""

    run_id: str
    mode: str
    status: str
    records_written: int
    records_committed: int
    pages_fetched: int
    requests: int
    retries: int
    source_total: int | None
    bronze_path: str
    high_watermark: dict[str, Any] | None
    error: str | None
    started_at: str
    finished_at: str
    resumed_from_page: int | None = None
    snapshot_id: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "records_written": self.records_written,
            "records_committed": self.records_committed,
            "pages_fetched": self.pages_fetched,
            "requests": self.requests,
            "retries": self.retries,
            "source_total": self.source_total,
            "error": self.error,
            "resumed_from_page": self.resumed_from_page,
        }


class ExtractionError(Exception):
    """The run stopped. Partial Bronze output may already exist."""

    def __init__(
        self,
        message: str,
        *,
        result: ExtractionResult | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.attempts = attempts or []


class SimulatedProcessCrash(Exception):
    """A killed worker. This is not an HTTP failure and must not be retried."""

    def __init__(self, message: str, *, result: ExtractionResult | None = None) -> None:
        super().__init__(message)
        self.result = result
