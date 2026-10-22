"""The extractor a scheduled script usually becomes on the first afternoon.

It performs one HTTP call, trusts the status code, and stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class NaiveFetch:
    status_code: int
    records: list[dict[str, Any]]
    total: int
    has_more: bool
    page: int
    page_size: int

    @property
    def missing(self) -> int:
        return self.total - len(self.records)


class NaiveExtractor:
    def __init__(self, client: httpx.Client, *, page_size: int = 50) -> None:
        self._client = client
        self._page_size = page_size

    def extract(self) -> NaiveFetch:
        response = self._client.get(
            "/api/orders",
            params={"page": 1, "page_size": self._page_size},
        )
        response.raise_for_status()
        body = response.json()
        return NaiveFetch(
            status_code=response.status_code,
            records=body["data"],
            total=int(body["total"]),
            has_more=bool(body["has_more"]),
            page=int(body["page"]),
            page_size=int(body["page_size"]),
        )
