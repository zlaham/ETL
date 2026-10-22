"""Pagination with retries and a checkpoint that cannot outrun Bronze.

The durability rule is local and strict: write and fsync the page, then
advance the checkpoint. The gap between those two steps is an at-least-once
window. Checkpointing does not create exactly-once ingestion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from src.ingestion import ExtractionError, ExtractionResult, SimulatedProcessCrash
from src.ingestion.checkpoints import Checkpoint, CheckpointStore, advance_watermark
from src.ingestion.retry_policy import RetryExecutor, RetryPolicy
from src.storage.bronze_writer import BronzeWriter

logger = logging.getLogger("ingestion.reliable")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


@dataclass
class CrashPlan:
    """Stop the worker after a durable Bronze write and before the checkpoint moves."""

    after_write_before_checkpoint_page: int | None = None


class ReliableExtractor:
    def __init__(
        self,
        client: httpx.Client,
        writer: BronzeWriter,
        checkpoint_store: CheckpointStore,
        retry_policy: RetryPolicy,
        *,
        page_size: int = 50,
        consistent_snapshot: bool = True,
    ) -> None:
        self._client = client
        self._writer = writer
        self._store = checkpoint_store
        self._retry = RetryExecutor(retry_policy)
        self._page_size = page_size
        self._consistent_snapshot = consistent_snapshot

    def extract(
        self,
        run_id: str,
        *,
        resume: bool = False,
        crash: CrashPlan | None = None,
    ) -> ExtractionResult:
        started = _now_iso()
        crash = crash or CrashPlan()
        checkpoint, start_page = self._open_run(run_id, resume)
        page = start_page
        snapshot_id = checkpoint.snapshot_id
        written = 0
        pages = 0
        attempts: list[dict[str, Any]] = []
        watermark = checkpoint.watermark()
        source_total: int | None = None

        while True:
            params: dict[str, Any] = {"page": page, "page_size": self._page_size}
            if self._consistent_snapshot and snapshot_id:
                params["snapshot_id"] = snapshot_id
            elif not self._consistent_snapshot:
                params["snapshot"] = "false"

            try:
                body, page_attempts = self._retry.get_json(
                    self._client,
                    "/api/orders",
                    params=params,
                    page=page,
                )
            except ExtractionError as exc:
                attempts.extend(exc.attempts)
                checkpoint.status = "failed"
                self._store.save(checkpoint)
                result = self._result(
                    checkpoint=checkpoint,
                    status="failed",
                    written=written,
                    pages=pages,
                    source_total=source_total,
                    error=str(exc),
                    started=started,
                    attempts=attempts,
                    resumed_from_page=start_page if resume else None,
                )
                raise ExtractionError(str(exc), result=result, attempts=attempts) from exc

            attempts.extend(page_attempts)
            snapshot_id = body.get("snapshot_id") or snapshot_id
            source_total = body.get("total", source_total)
            records = body["data"]
            if not records:
                break

            try:
                self._writer.write_records(records, run_id=run_id)
            except OSError as exc:
                checkpoint.status = "failed"
                self._store.save(checkpoint)
                result = self._result(
                    checkpoint=checkpoint,
                    status="failed",
                    written=written,
                    pages=pages,
                    source_total=source_total,
                    error=f"Bronze write failed on page {page}: {exc}",
                    started=started,
                    attempts=attempts,
                    resumed_from_page=start_page if resume else None,
                )
                raise ExtractionError(result.error or "bronze write failed", result=result) from exc

            # The page is on disk. The checkpoint does not know that yet.
            if crash.after_write_before_checkpoint_page == page:
                checkpoint.status = "interrupted"
                checkpoint.snapshot_id = snapshot_id
                self._store.save(checkpoint)
                written += len(records)
                result = self._result(
                    checkpoint=checkpoint,
                    status="interrupted",
                    written=written,
                    pages=pages,
                    source_total=source_total,
                    error=(
                        f"Process stopped after persisting page {page} "
                        "and before the checkpoint advanced."
                    ),
                    started=started,
                    attempts=attempts,
                    resumed_from_page=start_page if resume else None,
                )
                raise SimulatedProcessCrash(result.error or "interrupted", result=result)

            watermark = advance_watermark(watermark, records)
            checkpoint.last_completed_page = page
            checkpoint.records_committed += len(records)
            checkpoint.snapshot_id = snapshot_id
            checkpoint.status = "in_progress"
            checkpoint.set_watermark(watermark)
            self._store.save(checkpoint)
            written += len(records)
            pages += 1
            logger.info(
                "page=%s committed=%s run=%s snapshot=%s",
                page,
                checkpoint.records_committed,
                run_id,
                snapshot_id,
            )
            if not body.get("has_more"):
                break
            page += 1

        checkpoint.status = "completed"
        self._store.save(checkpoint)
        return self._result(
            checkpoint=checkpoint,
            status="success",
            written=written,
            pages=pages,
            source_total=source_total,
            error=None,
            started=started,
            attempts=attempts,
            resumed_from_page=start_page if resume else None,
        )

    def _open_run(self, run_id: str, resume: bool) -> tuple[Checkpoint, int]:
        if not resume:
            checkpoint = Checkpoint.start(run_id, mode="full")
            self._store.save(checkpoint)
            self._writer.reset_run(run_id)
            return checkpoint, 1

        checkpoint = self._store.load(run_id)
        if checkpoint is None:
            raise ExtractionError(f"No checkpoint to resume for {run_id}")
        if checkpoint.status == "completed":
            raise ExtractionError(f"Run {run_id} is already completed")
        start_page = checkpoint.last_completed_page + 1
        if start_page > 1 and self._consistent_snapshot and not checkpoint.snapshot_id:
            raise ExtractionError(
                "Checkpoint has no snapshot_id. "
                "Refusing to resume offset pagination without the original snapshot."
            )
        logger.info("resuming run=%s from page=%s", run_id, start_page)
        return checkpoint, start_page

    def _result(
        self,
        *,
        checkpoint: Checkpoint,
        status: str,
        written: int,
        pages: int,
        source_total: int | None,
        error: str | None,
        started: str,
        attempts: list[dict[str, Any]],
        resumed_from_page: int | None,
    ) -> ExtractionResult:
        watermark = checkpoint.watermark()
        high = None if watermark is None else {"updated_at": watermark[0], "order_id": watermark[1]}
        return ExtractionResult(
            run_id=checkpoint.run_id,
            mode=checkpoint.mode,
            status=status,
            records_written=written,
            records_committed=checkpoint.records_committed,
            pages_fetched=pages,
            requests=len(attempts),
            retries=sum(1 for item in attempts if item["outcome"] == "retry"),
            source_total=source_total,
            bronze_path=str(self._writer.path_for(checkpoint.run_id)),
            high_watermark=high,
            error=error,
            started_at=started,
            finished_at=_now_iso(),
            resumed_from_page=resumed_from_page,
            snapshot_id=checkpoint.snapshot_id,
            attempts=attempts,
        )
