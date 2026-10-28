"""Integration tests over the built snapshot, plus validation behaviour.

These read ``data/processed/*.parquet``; they are skipped if the pipeline has not
been run yet. The fixture-driven end-to-end contract test lives in
``test_contract.py`` and does not need the snapshot.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import forecast as forecast_router
from app.services.data_store import PROCESSED_ACTUALS_PATH, PROCESSED_FORECAST_PATH

SNAPSHOT_READY = PROCESSED_FORECAST_PATH.exists() and PROCESSED_ACTUALS_PATH.exists()

pytestmark = pytest.mark.skipif(
    not SNAPSHOT_READY, reason="processed snapshot missing; run scripts/fetch_data.py"
)

#: Every path the API is expected to expose (used by the /api/docs check).
EXPECTED_PATHS = {
    "/api/health",
    "/api/meta",
    "/api/forecast/decision",
    "/api/forecast/vintages",
    "/api/accuracy/summary",
    "/api/accuracy/daily",
    "/api/accuracy/by-hour",
    "/api/accuracy/distribution",
    "/api/accuracy/by-horizon",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# orientation
# ---------------------------------------------------------------------------
def test_health_reports_data_available(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["dataAvailable"] is True


def test_meta_states_the_cutoff_is_an_assumption(client):
    body = client.get("/api/meta").json()
    assert body["defaultCutoffLocalTime"] == "09:00"
    assert "assumption" in body["cutoffNote"]
    assert "gate closure" in body["cutoffNote"]
    assert body["resolution"]["forecastIntervalMinutes"] == 60
    assert body["resolution"]["settlementHalfHoursPerForecastValue"] == 2
    assert body["calibrationWarmup"]["to"] == "2025-12-31"
    assert body["dataAvailable"] is True


def test_openapi_documents_every_endpoint(client):
    """Done-when: /api/docs lists all built endpoints."""
    schema = client.get("/api/openapi.json").json()
    assert EXPECTED_PATHS <= set(schema["paths"])
    docs = client.get("/api/docs")
    assert docs.status_code == 200


# ---------------------------------------------------------------------------
# decision view
# ---------------------------------------------------------------------------
def test_decision_endpoint_returns_a_full_half_hour_grid(client):
    body = client.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"}).json()
    assert body["deliveryDate"] == "2026-01-15"
    assert len(body["rows"]) == 48
    assert body["counts"]["nForecastIntervals"] == 24
    assert body["dailyEnergy"]["partial"] is False
    assert body["dailyEnergy"]["unavailable"] is False
    assert body["calibrationMode"] == "decision_time"
    assert body["calibrationN"] == body["calibration"]["nIntervals"]
    # Every row carries a forecast, both bounds and an error.
    for row in body["rows"]:
        assert row["forecastMw"] is not None
        assert row["lowerBoundMw"] is not None
        assert row["upperBoundMw"] is not None
        assert row["errorMw"] is not None
        assert row["forecastMwh"] == pytest.approx(row["forecastMw"] * 0.5)


def test_decision_horizon_and_forecast_age_are_reported_separately(client):
    body = client.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"}).json()
    row = body["rows"][0]
    assert row["horizonHours"] is not None
    assert row["forecastAgeHours"] is not None
    assert row["horizonHours"] != row["forecastAgeHours"]


def test_decision_signal_is_never_negative(client):
    body = client.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"}).json()
    for row in body["rows"]:
        assert row["lowerBoundMw"] >= 0
        assert row["upperBoundMw"] >= 0


def test_calibration_mode_is_reported_and_available(client):
    body = client.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"}).json()
    calibration = body["calibration"]
    assert calibration["mode"] == "decision_time"
    assert calibration["strictNoLookahead"] is True
    assert calibration["available"] is True
    assert calibration["nDays"] >= 7
    assert "p90" in calibration["percentilesMw"]


def test_retrospective_mode_is_labeled(client):
    body = client.get(
        "/api/forecast/decision",
        params={"delivery_date": "2026-01-15", "mode": "retrospective"},
    ).json()
    assert body["calibration"]["mode"] == "retrospective"
    assert body["calibration"]["strictNoLookahead"] is False


def _utc(value: str) -> datetime:
    """ISO-8601 to datetime; the trailing ``Z`` is normalised (Python < 3.11 cannot)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_decision_cutoff_is_honoured(client):
    """An early cutoff must not see a later vintage, and never the future."""
    late = client.get(
        "/api/forecast/decision",
        params={"delivery_date": "2026-01-15", "cutoff": "18:00"},
    ).json()
    early = client.get(
        "/api/forecast/decision",
        params={"delivery_date": "2026-01-15", "cutoff": "01:00"},
    ).json()
    assert late["cutoffUtc"] != early["cutoffUtc"]

    for body in (early, late):
        cutoff = _utc(body["cutoffUtc"])
        for row in body["rows"]:
            if row["publishTime"] is None:
                assert row["forecastMw"] is None
            else:
                assert _utc(row["publishTime"]) <= cutoff

    early_with_forecast = sum(1 for r in early["rows"] if r["forecastMw"] is not None)
    late_with_forecast = sum(1 for r in late["rows"] if r["forecastMw"] is not None)
    assert early_with_forecast <= late_with_forecast


# ---------------------------------------------------------------------------
# all-vintages view
# ---------------------------------------------------------------------------
def test_vintages_endpoint_marks_the_selected_vintage(client):
    body = client.get("/api/forecast/vintages", params={"delivery_date": "2026-01-15"}).json()
    assert body["dataset"] == "all_vintages"
    assert body["counts"]["intervals"] == 24
    assert body["counts"]["vintages"] >= body["counts"]["selectedVintages"]
    # At most one vintage per interval is the one the client saw at the cutoff.
    for interval in body["intervals"]:
        assert sum(v["selected"] for v in interval["vintages"]) <= 1
        for vintage in interval["vintages"]:
            assert vintage["predictive"] == (vintage["horizonHours"] > 0)
    assert body["counts"]["vintagesAfterCutoff"] >= 0


# ---------------------------------------------------------------------------
# accuracy view
# ---------------------------------------------------------------------------
def test_accuracy_summary_reports_both_sample_sizes(client):
    body = client.get("/api/accuracy/summary").json()
    counts = body["counts"]
    assert counts["nDays"] == 31
    assert counts["nHalfHours"] == 31 * 48
    # The independent sample is the distinct hourly forecast intervals.
    assert counts["nForecastIntervals"] == counts["nHalfHours"] // 2
    assert body["decisionTime"]["n"] == counts["nHalfHours"]
    assert body["nativeHourly"]["n"] == counts["nForecastIntervals"]

    # Coverage is validated out of sample and reports both sizes.
    coverage = body["coverage"]
    assert coverage["lowerBoundCoverage"] is not None
    assert coverage["nIntervals"] > 0
    assert coverage["nDays"] > 0
    assert coverage["bandCoverage"] <= coverage["lowerBoundCoverage"] + 1e-9
    assert coverage["target"] == 0.9

    by_horizon = body["coverageByHorizon"]
    assert by_horizon["groups"]
    assert "materialVariation" in by_horizon

    calibration = body["calibration"]
    assert calibration["label"]
    assert calibration["pooled"] is True
    assert calibration["pooledNote"]
    assert calibration["boundsMw"] is not None


def test_accuracy_summary_respects_the_window(client):
    body = client.get(
        "/api/accuracy/summary", params={"from": "2026-01-01", "to": "2026-01-07"}
    ).json()
    assert body["counts"]["nDays"] == 7
    assert body["counts"]["nHalfHours"] == 7 * 48


def test_accuracy_series_endpoints(client):
    daily = client.get("/api/accuracy/daily").json()
    assert len(daily["series"]) == 31
    assert daily["series"][0]["deliveryDate"] == "2026-01-01"

    by_hour = client.get("/api/accuracy/by-hour").json()
    assert len(by_hour["series"]) == 24


def test_accuracy_distribution(client):
    body = client.get("/api/accuracy/distribution").json()
    assert body["histogram"]["n"] > 0
    assert "p90" in body["absoluteErrorPercentilesMw"]


def test_by_horizon_reports_records_and_intervals(client):
    body = client.get("/api/accuracy/by-horizon").json()
    assert body["dataset"] == "all_vintages"
    # Records published at or after their target time are excluded and counted.
    assert body["excludedRecords"] > 0
    assert body["excludedHorizonRangeHours"]["max"] <= 0
    assert len(body["buckets"]) >= 1
    for bucket in body["buckets"]:
        # Several vintages share a target interval, so records outnumber intervals.
        assert bucket["recordCount"] >= bucket["uniqueIntervalCount"]


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/forecast/decision", {"delivery_date": "2026-01-15", "mode": "cheat"}),
        ("/api/forecast/decision", {"delivery_date": "2026-01-15", "cutoff": "9am"}),
        ("/api/forecast/decision", {"delivery_date": "2026-03-01"}),
        ("/api/forecast/decision", {"delivery_date": "2025-12-31"}),
        ("/api/forecast/vintages", {"delivery_date": "2026-02-01"}),
        ("/api/forecast/vintages", {"delivery_date": "2026-01-15", "cutoff": "24:00"}),
        ("/api/accuracy/summary", {"mode": "cheat"}),
        ("/api/accuracy/summary", {"cutoff": "noon"}),
        ("/api/accuracy/summary", {"from": "2026-01-10", "to": "2026-01-01"}),
        ("/api/accuracy/summary", {"from": "2026-01-01", "to": "2026-02-01"}),
        ("/api/accuracy/daily", {"to": "2026-04-01"}),
        ("/api/accuracy/by-hour", {"mode": "cheat"}),
        ("/api/accuracy/distribution", {"from": "2025-12-01"}),
    ],
)
def test_invalid_input_is_rejected_with_422(client, path, params):
    response = client.get(path, params=params)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]


def test_valid_day_without_data_is_404(client, monkeypatch):
    """A well-formed January request the snapshot cannot answer is a 404."""
    empty = pd.DataFrame({"delivery_date": [date(2026, 1, 15)]}).iloc[0:0]
    monkeypatch.setattr(forecast_router, "get_decision_dataset", lambda cutoff: empty)
    response = client.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"})
    assert response.status_code == 404
    assert "2026-01-15" in response.json()["detail"]
