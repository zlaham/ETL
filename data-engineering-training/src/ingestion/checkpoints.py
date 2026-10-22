"""Checkpoints and watermarks.

A checkpoint records pages whose bytes are already durable in Bronze.
A watermark records the source cursor a future incremental run may start from.
They are different files because they answer different questions.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


@dataclass(frozen=True)
class Cursor:
    """Composite source cursor. order_id breaks updated_at ties."""

    updated_at: str
    order_id: int

    def as_dict(self) -> dict[str, Any]:
        return {"updated_at": self.updated_at, "order_id": self.order_id}

    def as_tuple(self) -> tuple[str, int]:
        return (self.updated_at, self.order_id)


def advance_watermark(
    current: tuple[str, int] | None,
    records: list[dict[str, Any]],
) -> tuple[str, int] | None:
    """Move a high-water mark forward. Never backward."""
    if not records:
        return current
    best = max((str(record["updated_at"]), int(record["order_id"])) for record in records)
    if current is None or best > current:
        return best
    return current


@dataclass
class Checkpoint:
    run_id: str
    source_system: str
    mode: str
    status: str
    last_completed_page: int
    records_committed: int
    snapshot_id: str | None
    watermark_updated_at: str | None
    watermark_order_id: int | None
    updated_at: str

    @classmethod
    def start(cls, run_id: str, mode: str) -> Checkpoint:
        return cls(
            run_id=run_id,
            source_system="orders_api",
            mode=mode,
            status="in_progress",
            last_completed_page=0,
            records_committed=0,
            snapshot_id=None,
            watermark_updated_at=None,
            watermark_order_id=None,
            updated_at=_now_iso(),
        )

    def watermark(self) -> tuple[str, int] | None:
        if self.watermark_updated_at is None or self.watermark_order_id is None:
            return None
        return (self.watermark_updated_at, self.watermark_order_id)

    def set_watermark(self, watermark: tuple[str, int] | None) -> None:
        if watermark is None:
            self.watermark_updated_at = None
            self.watermark_order_id = None
            return
        self.watermark_updated_at, self.watermark_order_id = watermark


class CheckpointStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        safe = run_id.replace("/", "_").replace("\\", "_")
        return self.directory / f"{safe}.checkpoint.json"

    def save(self, checkpoint: Checkpoint) -> None:
        """Atomically replace the checkpoint file. This is not a Bronze write."""
        checkpoint.updated_at = _now_iso()
        path = self.path_for(checkpoint.run_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(checkpoint), indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def load(self, run_id: str) -> Checkpoint | None:
        path = self.path_for(run_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Checkpoint(**payload)


class WatermarkStore:
    """The cursor that outlives a single run."""

    def __init__(self, directory: Path, name: str = "orders_watermark.json") -> None:
        self.path = Path(directory) / name
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Cursor | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        cursor = payload["cursor"]
        return Cursor(updated_at=str(cursor["updated_at"]), order_id=int(cursor["order_id"]))

    def save(self, cursor: Cursor, *, run_id: str) -> None:
        payload = {
            "source_system": "orders_api",
            "cursor": cursor.as_dict(),
            "updated_by_run_id": run_id,
            "saved_at": _now_iso(),
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
