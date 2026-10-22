"""Retry transient HTTP failures without pretending every error is transient.

Delays are short on purpose. A classroom cannot wait 30 seconds, and a
production Retry-After often would. The policy shape is the real lesson.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from src.ingestion import ExtractionError

logger = logging.getLogger("ingestion.retry")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 0.4
    min_interval_seconds: float = 0.0
    retryable_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


class RetryExecutor:
    """Sequential retries plus optional client-side pacing."""

    def __init__(self, policy: RetryPolicy) -> None:
        self.policy = policy
        self._last_request_at = 0.0

    def get_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        params: dict[str, Any],
        page: int | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        last_response: httpx.Response | None = None

        for attempt in range(1, self.policy.max_attempts + 1):
            self._pace()
            try:
                response = client.get(url, params=params)
            except httpx.TransportError as exc:
                delay = _backoff(self.policy, attempt)
                attempts.append(_attempt(page, attempt, None, delay, "retry"))
                logger.warning("transport error on page %s attempt %s: %s", page, attempt, exc)
                if attempt == self.policy.max_attempts:
                    raise ExtractionError(
                        f"Transport error on page {page} after {attempt} attempt(s): {exc}",
                        attempts=attempts,
                    ) from exc
                time.sleep(delay)
                continue

            self._last_request_at = time.monotonic()
            last_response = response
            retryable = response.status_code in self.policy.retryable_statuses
            if retryable and attempt < self.policy.max_attempts:
                delay = _retry_delay(response, self.policy, attempt)
                attempts.append(_attempt(page, attempt, response.status_code, delay, "retry"))
                logger.info(
                    "page=%s attempt=%s status=%s action=retry delay=%.3fs",
                    page,
                    attempt,
                    response.status_code,
                    delay,
                )
                time.sleep(delay)
                continue

            outcome = "success" if response.status_code < 400 else "failed"
            attempts.append(_attempt(page, attempt, response.status_code, 0.0, outcome))
            break

        if last_response is None or last_response.status_code >= 400:
            status = None if last_response is None else last_response.status_code
            detail = _error_detail(last_response)
            raise ExtractionError(
                f"HTTP {status} on page {page} after {len(attempts)} attempt(s). {detail}".strip(),
                attempts=attempts,
            )
        if any(item["outcome"] == "retry" for item in attempts):
            logger.info("page=%s recovered on attempt %s", page, len(attempts))
        return last_response.json(), attempts

    def _pace(self) -> None:
        interval = self.policy.min_interval_seconds
        if interval <= 0 or self._last_request_at == 0:
            return
        remaining = interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)


def _retry_delay(response: httpx.Response, policy: RetryPolicy, attempt: int) -> float:
    """Prefer the server's Retry-After, and never wait less than the backoff."""
    header = response.headers.get("retry-after")
    retry_after = float(header) if header else 0.0
    return max(retry_after, _backoff(policy, attempt))


def _backoff(policy: RetryPolicy, attempt: int) -> float:
    return min(policy.max_delay_seconds, policy.base_delay_seconds * (2 ** (attempt - 1)))


def _attempt(
    page: int | None,
    attempt: int,
    status_code: int | None,
    delay_seconds: float,
    outcome: str,
) -> dict[str, Any]:
    return {
        "page": page,
        "attempt": attempt,
        "status_code": status_code,
        "delay_seconds": round(delay_seconds, 3),
        "outcome": outcome,
    }


def _error_detail(response: httpx.Response | None) -> str:
    if response is None:
        return ""
    try:
        message = response.json().get("message")
    except Exception:
        return ""
    return str(message or "")
