"""Incremental extraction with a composite (updated_at, order_id) cursor.

The watermark is saved only after the run finishes. A failure in the middle
leaves the old cursor in place, so the next run reads the same window again.
Rows already appended to Bronze can appear twice. That is at-least-once.

Limitations this module does not remove:

- Deletes are invisible.
- A change that moves updated_at backward is invisible.
- Polls collapse every intermediate state into the latest row.
- Ties require order_id. A timestamp alone is not a cursor.
- This is not a change-data-capture log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.ingestion import ExtractionError, ExtractionResult
from src.ingestion.checkpoints import Cursor, WatermarkStore
from src.ingestion.retry_policy import RetryExecutor, RetryPolicy
from src.storage.bronze_writer import BronzeWriter

logger = logging.getLogger("ingestion.incremental")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class IncrementalExtractor:
    def __init__(
        self,
        client: httpx.Client,
        writer: BronzeWriter,
        watermark_store: WatermarkStore,
        retry_policy: RetryPolicy,
        *,
        page_size: int = 50,
    ) -> None:
        self._client = client
        self._writer = writer
        self._watermarks = watermark_store
        self._retry = RetryExecutor(retry_policy)
        self._page_size = page_size

    def extract(self, run_id: str) -> ExtractionResult:
        stored = self._watermarks.load()
        if stored is None:
            raise ExtractionError(
                "No watermark is saved. Run a full extraction and save its high "
                "watermark before starting an incremental sync."
            )

        started = _now_iso()
        self._writer.reset_run(run_id)
        cursor = stored
        written = 0
        pages = 0
        attempts: list[dict[str, Any]] = []
        source_total: int | None = None

        while True:
            params = {
                "updated_after": cursor.updated_at,
                "after_id": cursor.order_id,
                "limit": self._page_size,
            }
            try:
                body, page_attempts = self._retry.get_json(
                    self._client,
                    "/api/orders",
                    params=params,
                    page=pages + 1,
                )
            except ExtractionError as exc:
                attempts.extend(exc.attempts)
                result = self._result(
                    run_id=run_id,
                    status="failed",
                    written=written,
                    pages=pages,
                    source_total=source_total,
                    cursor=stored,
                    error=str(exc),
                    started=started,
                    attempts=attempts,
                )
                raise ExtractionError(str(exc), result=result, attempts=attempts) from exc

            attempts.extend(page_attempts)
            if source_total is None:
                source_total = body.get("total_matching")
            records = body["data"]
            if not records:
                break

            self._writer.write_records(records, run_id=run_id)
            written += len(records)
            pages += 1
            last = records[-1]
            cursor = Cursor(updated_at=str(last["updated_at"]), order_id=int(last["order_id"]))
            logger.info(
                "incremental page=%s wrote=%s cursor=%s|%s",
                pages,
                len(records),
                cursor.updated_at,
                cursor.order_id,
            )
            if not body.get("has_more"):
                break

        # Advance the stored cursor only after every matched page has been written.
        if written:
            self._watermarks.save(cursor, run_id=run_id)
        return self._result(
            run_id=run_id,
            status="success",
            written=written,
            pages=pages,
            source_total=source_total,
            cursor=cursor if written else stored,
            error=None,
            started=started,
            attempts=attempts,
        )

    def _result(
        self,
        *,
        run_id: str,
        status: str,
        written: int,
        pages: int,
        source_total: int | None,
        cursor: Cursor,
        error: str | None,
        started: str,
        attempts: list[dict[str, Any]],
    ) -> ExtractionResult:
        return ExtractionResult(
            run_id=run_id,
            mode="incremental",
            status=status,
            records_written=written,
            records_committed=written if status == "success" else 0,
            pages_fetched=pages,
            requests=len(attempts),
            retries=sum(1 for item in attempts if item["outcome"] == "retry"),
            source_total=source_total,
            bronze_path=str(self._writer.path_for(run_id)),
            high_watermark=cursor.as_dict(),
            error=error,
            started_at=started,
            finished_at=_now_iso(),
            attempts=attempts,
        )
