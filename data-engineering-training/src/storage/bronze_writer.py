"""Append-only Bronze writer.

Bronze stores the source payload exactly as it arrived, wrapped in
ingestion metadata. It does not clean, type, or deduplicate that payload.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class BronzeWriter:
    """Write one JSON object per line. Flush and fsync after every page."""

    def __init__(self, directory: Path, *, source_system: str = "orders_api") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.source_system = source_system

    def path_for(self, run_id: str) -> Path:
        safe = run_id.replace("/", "_").replace("\\", "_")
        return self.directory / f"{safe}.jsonl"

    def reset_run(self, run_id: str) -> None:
        """Remove a previous file for this run so a re-executed demo starts clean."""
        path = self.path_for(run_id)
        if path.exists():
            path.unlink()

    def write_records(
        self,
        records: list[dict[str, Any]],
        *,
        run_id: str,
        ingested_at: str | None = None,
    ) -> int:
        """Append a page. The caller may checkpoint only after this returns."""
        if not records:
            return 0
        stamped_at = ingested_at or _now_iso()
        path = self.path_for(run_id)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                if "order_id" not in record:
                    raise ValueError("Refusing to ingest an order with no order_id")
                envelope = {
                    "source_system": self.source_system,
                    "ingested_at": stamped_at,
                    "run_id": run_id,
                    "source_record_id": record["order_id"],
                    "payload": copy.deepcopy(record),
                }
                handle.write(json.dumps(envelope, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return len(records)

    def read_envelopes(self, run_id: str) -> list[dict[str, Any]]:
        path = self.path_for(run_id)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
