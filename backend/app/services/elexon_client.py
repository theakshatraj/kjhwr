"""Minimal, dependency-light client for the Elexon BMRS REST API.

Two things matter for this project:

1. ``WINDFOR`` must be filtered on **publish time**
   (``publishDateTimeFrom`` / ``publishDateTimeTo``). If those parameter names
   are wrong the endpoint silently ignores them and returns the *latest*
   forecast only, which would destroy the whole decision-time analysis.
2. Requests must be chunked, because the stream endpoints cap the range that
   can be requested in a single call.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

import requests

from app.config import ELEXON_BASE_URL

logger = logging.getLogger(__name__)

#: Elexon rejects stream requests wider than this. Verified empirically by
#: ``scripts/feasibility_spike.py`` (evidence in ``data/feasibility_report.txt``).
MAX_RANGE_DAYS = 7

#: Elexon asks clients to stay well inside their rate limit; 429s are retried.
REQUEST_PAUSE_SECONDS = 0.35

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


class ElexonError(RuntimeError):
    """Raised when the Elexon API cannot be read after all retries."""


def _iso_z(value: str | datetime) -> str:
    """Normalise any datetime-ish value to the ISO-8601 Z form Elexon accepts."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = value.strip()
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")] + "Z"
    return text


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class ElexonClient:
    """Thin wrapper around the BMRS ``datasets`` stream endpoints."""

    def __init__(self, base_url: str = ELEXON_BASE_URL, timeout: int = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.request_count = 0
        #: Every successful request, recorded verbatim for provenance.
        self.request_log: list[dict[str, Any]] = []

    # -- transport ---------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self.request_count += 1
                if response.status_code == 200:
                    payload = response.json()
                    if not isinstance(payload, list):
                        raise ElexonError(
                            f"Expected a list from {path}, got {type(payload).__name__}"
                        )
                    self.request_log.append(
                        {"url": url, "params": dict(params), "rows": len(payload)}
                    )
                    time.sleep(REQUEST_PAUSE_SECONDS)
                    return payload
                if response.status_code in RETRYABLE_STATUS:
                    last_error = ElexonError(
                        f"HTTP {response.status_code} for {path}: {response.text[:200]}"
                    )
                else:
                    raise ElexonError(
                        f"HTTP {response.status_code} for {path} "
                        f"params={params}: {response.text[:300]}"
                    )
            except requests.RequestException as exc:  # network hiccup
                last_error = exc

            backoff = 2 ** (attempt - 1)
            logger.warning(
                "Elexon request failed (attempt %s/%s) %s %s - retrying in %ss: %s",
                attempt,
                MAX_ATTEMPTS,
                path,
                params,
                backoff,
                last_error,
            )
            time.sleep(backoff)

        raise ElexonError(f"Giving up on {path} params={params}: {last_error}")

    # -- date chunking -----------------------------------------------------
    @staticmethod
    def _chunks(start_iso: str, end_iso: str, days: int = MAX_RANGE_DAYS) -> Iterator[tuple[str, str]]:
        """Split a datetime window into <= ``days`` chunks."""
        start, end = _parse_iso(start_iso), _parse_iso(end_iso)
        step = timedelta(days=days)
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + step, end)
            yield _iso_z(cursor), _iso_z(chunk_end)
            cursor = chunk_end

    @staticmethod
    def _date_chunks(start_day: str, end_day: str, days: int = MAX_RANGE_DAYS * 4) -> Iterator[tuple[str, str]]:
        """Split an inclusive calendar-date window into <= ``days`` chunks."""
        start = date.fromisoformat(start_day)
        end = date.fromisoformat(end_day)
        step = timedelta(days=days)
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + step - timedelta(days=1), end)
            yield cursor.isoformat(), chunk_end.isoformat()
            cursor = chunk_end + timedelta(days=1)

    # -- datasets ----------------------------------------------------------
    def fetch_wind_forecasts(
        self, publish_from: str, publish_to: str, chunk_days: int = MAX_RANGE_DAYS
    ) -> list[dict[str, Any]]:
        """RAW WINDFOR records for a *publish* window.

        Returns every published vintage, including multiple ``publishTime``
        versions of the same ``startTime``.
        """
        records: list[dict[str, Any]] = []
        for chunk_from, chunk_to in self._chunks(publish_from, publish_to, chunk_days):
            logger.info("WINDFOR publish %s -> %s", chunk_from, chunk_to)
            records.extend(
                self._get(
                    "/datasets/WINDFOR/stream",
                    {"publishDateTimeFrom": chunk_from, "publishDateTimeTo": chunk_to},
                )
            )
        return records

    def fetch_wind_actuals(
        self, settlement_from: str, settlement_to: str, chunk_days: int = MAX_RANGE_DAYS
    ) -> list[dict[str, Any]]:
        """FUELHH records for ``fuelType == WIND``, filtered by **settlement date**.

        Settlement-date filtering returns exactly one row per settlement period
        (48 per normal London day), so no de-duplication of published revisions
        is needed. ``settlementDate`` is a London calendar date.
        """
        records: list[dict[str, Any]] = []
        for chunk_from, chunk_to in self._date_chunks(settlement_from, settlement_to, chunk_days):
            logger.info("FUELHH WIND settlement %s -> %s", chunk_from, chunk_to)
            records.extend(
                self._get(
                    "/datasets/FUELHH/stream",
                    {
                        "settlementDateFrom": chunk_from,
                        "settlementDateTo": chunk_to,
                        "fuelType": "WIND",
                    },
                )
            )
        return records
