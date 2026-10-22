"""In-process Orders API.

httpx.MockTransport exercises real request and response semantics without
a socket, a server process, or a network. Failures are injected, deterministic,
and cleared by reset_session() or restore().
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import httpx

MAX_PAGE_SIZE = 200


@dataclass
class PlannedFailure:
    status_code: int
    remaining: int
    page: int | None = None
    retry_after: str | None = None


@dataclass
class PlannedMutation:
    after_request: int
    order_id: int
    applied: bool = False


@dataclass
class OrdersApi:
    """Mutable operational store plus the HTTP contract in front of it."""

    _seed_orders: list[dict[str, Any]]
    _orders: list[dict[str, Any]] = field(init=False)
    _failures: list[PlannedFailure] = field(default_factory=list)
    _mutations: list[PlannedMutation] = field(default_factory=list)
    _snapshots: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _snapshot_seq: int = 0
    _request_log: list[dict[str, Any]] = field(default_factory=list)
    _orders_request_count: int = 0

    def __post_init__(self) -> None:
        self._orders = copy.deepcopy(self._seed_orders)

    @classmethod
    def from_orders(cls, orders: list[dict[str, Any]]) -> OrdersApi:
        return cls(_seed_orders=copy.deepcopy(orders))

    @property
    def order_count(self) -> int:
        return len(self._orders)

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handle),
            base_url="https://orders.internal",
            timeout=5.0,
        )

    def restore(self) -> None:
        """Put the operational table and the HTTP session back to the seed."""
        self._orders = copy.deepcopy(self._seed_orders)
        self.reset_session()

    def reset_session(self) -> None:
        """Clear failures, snapshots, mutations, and logs. Keep current orders."""
        self._failures.clear()
        self._mutations.clear()
        self._snapshots.clear()
        self._snapshot_seq = 0
        self._request_log.clear()
        self._orders_request_count = 0

    def drop_snapshots(self) -> None:
        """Simulate an expired server-side pagination context."""
        self._snapshots.clear()

    def fail_request(
        self,
        status_code: int,
        *,
        times: int = 1,
        page: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        """Queue a deterministic failure. `page` limits it to that page number."""
        if times < 1:
            raise ValueError("times must be positive")
        if status_code == 429 and retry_after is None:
            retry_after = "0.02"
        self._failures.append(
            PlannedFailure(
                status_code=status_code,
                remaining=times,
                page=page,
                retry_after=retry_after,
            )
        )

    def delete_after_request(self, request_number: int, order_id: int) -> None:
        """Delete an order after the Nth /api/orders request has been served."""
        if request_number < 1:
            raise ValueError("request_number is 1-based")
        self._mutations.append(PlannedMutation(after_request=request_number, order_id=order_id))

    def get_order(self, order_id: int) -> dict[str, Any]:
        return copy.deepcopy(self._must(order_id))

    def update_order(self, order_id: int, **changes: Any) -> dict[str, Any]:
        """Apply a source change. The caller supplies updated_at on purpose."""
        if "updated_at" not in changes:
            raise ValueError("Pass updated_at explicitly so the demo clock stays fixed")
        order = self._must(order_id)
        order.update(changes)
        return copy.deepcopy(order)

    def add_orders(self, orders: list[dict[str, Any]]) -> None:
        existing = {int(order["order_id"]) for order in self._orders}
        for order in orders:
            order_id = int(order["order_id"])
            if order_id in existing:
                raise ValueError(f"Duplicate order_id {order_id}")
            self._orders.append(copy.deepcopy(order))
            existing.add(order_id)

    def delete_order(self, order_id: int) -> None:
        before = len(self._orders)
        self._orders = [order for order in self._orders if int(order["order_id"]) != order_id]
        if len(self._orders) == before:
            raise KeyError(order_id)

    def recent_requests(self) -> list[dict[str, Any]]:
        return list(self._request_log)

    def contract(self) -> dict[str, Any]:
        """The guarantees this source is willing to make. Read them narrowly."""
        return {
            "endpoint": "GET https://orders.internal/api/orders",
            "identity": "order_id",
            "full_extract": {
                "params": ["page", "page_size", "snapshot_id"],
                "ordering": "order_id ascending",
                "snapshot": (
                    "The first request opens a snapshot. Later pages must send that snapshot_id."
                ),
            },
            "incremental_extract": {
                "params": ["updated_after", "after_id", "limit"],
                "ordering": "(updated_at, order_id) ascending",
                "predicate": (
                    "updated_at > updated_after "
                    "OR (updated_at == updated_after AND order_id > after_id)"
                ),
            },
            "max_page_size": MAX_PAGE_SIZE,
            "empty_result": "HTTP 200 with data: []",
            "errors": {
                "429": "Retryable. Retry-After is a number of seconds. The demo compresses it.",
                "500": "Retryable transient failure.",
                "409": "Unknown snapshot_id. Not retryable. Do not open a fresh offset window.",
            },
            "guarantees": [
                "order_id is unique and stable.",
                "A snapshot_id pages a frozen order_id sequence for this process.",
                "The incremental predicate is strict and uses both updated_at and order_id.",
                "An empty match is HTTP 200 with an empty data array, not an error.",
            ],
            "does_not_guarantee": [
                "Offset pages of the live table while orders are inserted or deleted.",
                "A delete feed. Removed orders simply disappear.",
                "updated_at only moves forward. A backdated correction is invisible.",
                "Intermediate states between two polls. You see the latest row only.",
                "Exactly-once delivery.",
                "A total that stays still once you leave the snapshot.",
            ],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        path = request.url.path
        if request.method == "GET" and path == "/api/orders/count":
            body = {"total": len(self._orders)}
            self._log(request, 200, params)
            return httpx.Response(200, json=body, headers={"x-request-id": self._next_request_id()})

        if request.method != "GET" or path != "/api/orders":
            body = {"error": "not_found", "message": f"No route for {request.method} {path}"}
            self._log(request, 404, params)
            return httpx.Response(404, json=body)

        self._orders_request_count += 1
        request_id = self._next_request_id()
        page = _optional_int(params.get("page"))
        failure = self._consume_failure(page)
        if failure is not None:
            payload: dict[str, Any] = {
                "error": "rate_limited" if failure.status_code == 429 else "transient_failure",
                "message": "Injected failure for the extraction demonstration",
                "page": page,
            }
            headers = {"x-request-id": request_id}
            if failure.retry_after is not None:
                headers["retry-after"] = failure.retry_after
                payload["retry_after_seconds"] = float(failure.retry_after)
            self._log(request, failure.status_code, params)
            return httpx.Response(failure.status_code, json=payload, headers=headers)

        status, payload, extra_headers = self._serve(params)
        self._log(request, status, params)
        if status < 400:
            self._apply_due_mutations()
        headers = {"x-request-id": request_id}
        headers.update(extra_headers)
        return httpx.Response(status, json=payload, headers=headers)

    def _serve(self, params: dict[str, str]) -> tuple[int, dict[str, Any], dict[str, str]]:
        if _is_incremental(params):
            return self._serve_incremental(params)
        return self._serve_page(params)

    def _serve_page(self, params: dict[str, str]) -> tuple[int, dict[str, Any], dict[str, str]]:
        page = _optional_int(params.get("page")) or 1
        page_size = _optional_int(params.get("page_size")) or 50
        if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
            return 400, {"error": "bad_request", "message": "Invalid page or page_size"}, {}

        snapshot_id = params.get("snapshot_id") or None
        consistent = params.get("snapshot", "true").lower() != "false"
        # Offset pages are only safe while `rows` is frozen. A live list shifts
        # under inserts and deletes, and a later page can skip a row that still exists.
        if snapshot_id:
            rows = self._snapshots.get(snapshot_id)
            if rows is None:
                return (
                    409,
                    {
                        "error": "snapshot_expired",
                        "message": (
                            f"Unknown snapshot_id {snapshot_id}. "
                            "Refusing to continue offset pagination on a new window."
                        ),
                    },
                    {},
                )
        elif consistent:
            self._snapshot_seq += 1
            snapshot_id = f"snap_{self._snapshot_seq:04d}"
            rows = sorted(copy.deepcopy(self._orders), key=lambda order: int(order["order_id"]))
            self._snapshots[snapshot_id] = rows
        else:
            snapshot_id = None
            rows = sorted(self._orders, key=lambda order: int(order["order_id"]))

        start = (page - 1) * page_size
        window = rows[start : start + page_size]
        body = {
            "data": copy.deepcopy(window),
            "page": page,
            "page_size": page_size,
            "total": len(rows),
            "has_more": start + page_size < len(rows),
            "snapshot_id": snapshot_id,
            "ordering": "order_id",
            "consistent_snapshot": snapshot_id is not None,
        }
        return 200, body, {}

    def _serve_incremental(self, params: dict[str, str]) -> tuple[int, dict[str, Any], dict[str, str]]:
        updated_after = params.get("updated_after") or None
        after_id = _optional_int(params.get("after_id"))
        limit = _optional_int(params.get("limit") or params.get("page_size")) or 50
        if limit < 1 or limit > MAX_PAGE_SIZE:
            return 400, {"error": "bad_request", "message": "Invalid limit"}, {}

        matched = [
            order
            for order in self._orders
            if _is_after(order, updated_after, after_id)
        ]
        matched.sort(key=lambda order: (str(order["updated_at"]), int(order["order_id"])))
        window = matched[:limit]
        next_cursor = None
        if window:
            last = window[-1]
            next_cursor = {"updated_at": last["updated_at"], "order_id": int(last["order_id"])}
        body = {
            "data": copy.deepcopy(window),
            "limit": limit,
            "returned": len(window),
            "has_more": len(matched) > limit,
            "next_cursor": next_cursor,
            "total_matching": len(matched),
            "ordering": "updated_at,order_id",
            "consistent_snapshot": False,
        }
        return 200, body, {}

    def _consume_failure(self, page: int | None) -> PlannedFailure | None:
        for planned in self._failures:
            if planned.remaining <= 0:
                continue
            if planned.page is not None and planned.page != page:
                continue
            planned.remaining -= 1
            return planned
        return None

    def _apply_due_mutations(self) -> None:
        for mutation in self._mutations:
            if mutation.applied or mutation.after_request != self._orders_request_count:
                continue
            self.delete_order(mutation.order_id)
            mutation.applied = True

    def _must(self, order_id: int) -> dict[str, Any]:
        for order in self._orders:
            if int(order["order_id"]) == order_id:
                return order
        raise KeyError(order_id)

    def _next_request_id(self) -> str:
        return f"req_{self._orders_request_count:04d}"

    def _log(self, request: httpx.Request, status_code: int, params: dict[str, str]) -> None:
        self._request_log.append(
            {
                "n": len(self._request_log) + 1,
                "method": request.method,
                "path": request.url.path,
                "params": dict(params),
                "status_code": status_code,
            }
        )


def _is_incremental(params: dict[str, str]) -> bool:
    return any(params.get(name) not in (None, "") for name in ("updated_after", "after_id", "limit"))


def _is_after(order: dict[str, Any], updated_after: str | None, after_id: int | None) -> bool:
    """Strict composite cursor: (updated_at, order_id) greater than the watermark."""
    if updated_after is None:
        return True
    stamp = str(order["updated_at"])
    if stamp > updated_after:
        return True
    if stamp == updated_after and after_id is not None and int(order["order_id"]) > after_id:
        return True
    return False


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
