"""Full extraction that follows pages and writes each page before the next.

The loop does not accumulate the source in a list. Five hundred orders would
fit. Fifty million should not have to.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.ingestion import ExtractionError, ExtractionResult
from src.ingestion.checkpoints import advance_watermark
from src.storage.bronze_writer import BronzeWriter

logger = logging.getLogger("ingestion.paginated")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class PaginatedExtractor:
    def __init__(
        self,
        client: httpx.Client,
        writer: BronzeWriter,
        *,
        page_size: int = 50,
        consistent_snapshot: bool = True,
    ) -> None:
        self._client = client
        self._writer = writer
        self._page_size = page_size
        self._consistent_snapshot = consistent_snapshot

    def extract(self, run_id: str) -> ExtractionResult:
        started = _now_iso()
        self._writer.reset_run(run_id)
        page = 1
        snapshot_id: str | None = None
        written = 0
        pages = 0
        watermark: tuple[str, int] | None = None
        source_total: int | None = None
        attempts: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {"page": page, "page_size": self._page_size}
            if self._consistent_snapshot and snapshot_id:
                params["snapshot_id"] = snapshot_id
            elif not self._consistent_snapshot:
                params["snapshot"] = "false"

            response = self._client.get("/api/orders", params=params)
            outcome = "success" if response.status_code < 400 else "failed"
            attempts.append(
                {
                    "page": page,
                    "attempt": 1,
                    "status_code": response.status_code,
                    "delay_seconds": 0.0,
                    "outcome": outcome,
                }
            )
            if response.status_code >= 400:
                detail = _detail(response)
                result = self._result(
                    run_id=run_id,
                    status="failed",
                    written=written,
                    pages=pages,
                    source_total=source_total,
                    watermark=watermark,
                    error=f"HTTP {response.status_code} on page {page}. {detail}".strip(),
                    started=started,
                    attempts=attempts,
                    snapshot_id=snapshot_id,
                )
                raise ExtractionError(result.error or "extraction failed", result=result)

            body = response.json()
            snapshot_id = body.get("snapshot_id") or snapshot_id
            source_total = body.get("total", source_total)
            records = body["data"]
            if records:
                self._writer.write_records(records, run_id=run_id)
                written += len(records)
                pages += 1
                watermark = advance_watermark(watermark, records)
                logger.info("page=%s wrote=%s run=%s", page, len(records), run_id)
            if not records or not body.get("has_more"):
                break
            page += 1

        return self._result(
            run_id=run_id,
            status="success",
            written=written,
            pages=pages,
            source_total=source_total,
            watermark=watermark,
            error=None,
            started=started,
            attempts=attempts,
            snapshot_id=snapshot_id,
        )

    def _result(
        self,
        *,
        run_id: str,
        status: str,
        written: int,
        pages: int,
        source_total: int | None,
        watermark: tuple[str, int] | None,
        error: str | None,
        started: str,
        attempts: list[dict[str, Any]],
        snapshot_id: str | None,
    ) -> ExtractionResult:
        high = None if watermark is None else {"updated_at": watermark[0], "order_id": watermark[1]}
        return ExtractionResult(
            run_id=run_id,
            mode="full",
            status=status,
            records_written=written,
            records_committed=written,
            pages_fetched=pages,
            requests=len(attempts),
            retries=0,
            source_total=source_total,
            bronze_path=str(self._writer.path_for(run_id)),
            high_watermark=high,
            error=error,
            started_at=started,
            finished_at=_now_iso(),
            snapshot_id=snapshot_id,
            attempts=attempts,
        )


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or "")
    except Exception:
        return ""
