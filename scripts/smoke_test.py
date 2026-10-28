#!/usr/bin/env python3
"""Smoke-test a deployed Wind Forecast Decision Portal instance.

Usage:
    python scripts/smoke_test.py <base_url>

Example:
    python scripts/smoke_test.py https://example.vercel.app

Phase 7 requires three checks against the live base URL:

  1. GET /api/health
  2. one decision-time query (15 January 2026 at the assumed 09:00 cutoff)
  3. GET /api/accuracy/summary for January 2026

Stdlib only so the script runs without the backend venv's extra packages.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 60
DELIVERY_DATE = "2026-01-15"
CUTOFF = "09:00"
WINDOW_FROM = "2026-01-01"
WINDOW_TO = "2026-01-31"


def get_json(base_url: str, path: str, query: dict[str, str] | None = None) -> tuple[int, Any]:
    url = base_url.rstrip("/") + path
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(body)
        except json.JSONDecodeError:
            parsed = body[:500]
        return exc.code, parsed


def get_status(base_url: str, path: str) -> int:
    url = base_url.rstrip("/") + path
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def fail(message: str) -> None:
    print(f"FAIL  {message}")


def ok(message: str) -> None:
    print(f"ok    {message}")


def test_health(base_url: str) -> bool:
    status, body = get_json(base_url, "/api/health")
    if status != 200:
        fail(f"health: HTTP {status} {body!r}")
        return False
    if not isinstance(body, dict) or body.get("status") != "ok":
        fail(f"health: unexpected body {body!r}")
        return False
    if body.get("dataAvailable") is not True:
        fail(f"health: processed snapshot not available ({body!r})")
        return False
    ok("health: status=ok, dataAvailable=true")
    return True


def test_decision(base_url: str) -> bool:
    status, body = get_json(
        base_url,
        "/api/forecast/decision",
        {
            "delivery_date": DELIVERY_DATE,
            "cutoff": CUTOFF,
            "mode": "decision_time",
        },
    )
    if status != 200:
        fail(f"decision: HTTP {status} {body!r}")
        return False
    if not isinstance(body, dict):
        fail(f"decision: expected an object, got {type(body).__name__}")
        return False
    rows = body.get("rows")
    if not isinstance(rows, list) or len(rows) != 48:
        fail(f"decision: expected 48 half-hours, got {0 if not isinstance(rows, list) else len(rows)}")
        return False
    with_forecast = sum(1 for row in rows if row.get("forecastMw") is not None)
    if with_forecast == 0:
        fail("decision: every interval is missing a forecast")
        return False
    if body.get("deliveryDate") != DELIVERY_DATE:
        fail(f"decision: deliveryDate {body.get('deliveryDate')!r} != {DELIVERY_DATE}")
        return False
    energy = (body.get("dailyEnergy") or {}).get("energyMwh")
    ok(
        f"decision: {DELIVERY_DATE} cutoff={body.get('cutoffLocalTime')} "
        f"intervals={len(rows)} withForecast={with_forecast} "
        f"energyMwh={energy} calibrationN={body.get('calibrationN')}"
    )
    return True


def test_accuracy(base_url: str) -> bool:
    status, body = get_json(
        base_url,
        "/api/accuracy/summary",
        {
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "cutoff": CUTOFF,
            "mode": "decision_time",
        },
    )
    if status != 200:
        fail(f"accuracy: HTTP {status} {body!r}")
        return False
    if not isinstance(body, dict):
        fail(f"accuracy: expected an object, got {type(body).__name__}")
        return False
    metrics = body.get("decisionTime") or {}
    bias = metrics.get("biasMw")
    mae = metrics.get("maeMw")
    if bias is None or mae is None:
        fail(f"accuracy: missing biasMw/maeMw in decisionTime ({metrics!r})")
        return False
    coverage = body.get("coverage") or {}
    signed = metrics.get("signedErrorPercentilesMw") or {}
    ok(
        f"accuracy: Jan 2026 biasMw={bias:.2f} maeMw={mae:.2f} "
        f"p90E={signed.get('p90')} lowerCoverage={coverage.get('lowerBoundCoverage')}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a deployed portal instance.")
    parser.add_argument("base_url", help="Live origin, e.g. https://example.vercel.app")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print(f"Smoke test  {base_url}")
    print("-" * 60)

    passed = True
    passed &= test_health(base_url)
    passed &= test_decision(base_url)
    passed &= test_accuracy(base_url)

    docs_status = get_status(base_url, "/api/docs")
    if docs_status == 200:
        ok("docs: /api/docs returned HTTP 200 (informational)")
    else:
        print(f"note  /api/docs returned HTTP {docs_status} (not a required check)")

    print("-" * 60)
    if passed:
        print("All required smoke checks passed.")
        return 0
    print("Smoke test failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
