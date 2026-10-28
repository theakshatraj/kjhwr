"""End-to-end contract test: fixture data -> decision selection -> metrics -> API JSON.

One test walks the whole path a real request takes:

  1. clean the hand-written Elexon fixtures,
  2. run the decision-time selection for 2026-01-15,
  3. check the resulting errors by hand (this is the metric, not a mock),
  4. call the live app with those fixtures injected and assert the JSON keys are
     exactly the fields declared in ``frontend/src/types.ts``.

The TypeScript file is the cross-language contract: if either side renames a
field, this test fails instead of the frontend breaking at runtime.
"""

from __future__ import annotations

import re
from datetime import date, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import forecast as forecast_router
from app.services.data_store import (
    PROCESSED_ACTUALS_PATH,
    PROCESSED_FORECAST_PATH,
    clean_actuals,
    clean_forecasts,
)
from app.services.decision_forecast import build_decision_dataset
from app.services.metrics import summary

TYPES_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types.ts"

INTERFACE_RE = re.compile(r"export interface (\w+) \{(.*?)\n\}", re.DOTALL)
FIELD_RE = re.compile(r"^\s*(\w+)\??\s*:", re.MULTILINE)


def declared_fields() -> dict[str, set[str]]:
    """``{interfaceName: {field, ...}}`` parsed from the TypeScript contract."""
    text = TYPES_PATH.read_text(encoding="utf-8")
    return {name: set(FIELD_RE.findall(body)) for name, body in INTERFACE_RE.findall(text)}


def assert_shape(payload: dict, interface: str, fields: dict[str, set[str]]) -> None:
    assert set(payload) == fields[interface], (
        f"{interface}: JSON keys {sorted(payload)} != declared {sorted(fields[interface])}"
    )


def test_end_to_end_fixture_to_api_matches_typescript_contract(
    monkeypatch, raw_forecast_records, raw_actual_records
):
    fields = declared_fields()

    # -- 1. fixture data ----------------------------------------------------
    forecasts = clean_forecasts(raw_forecast_records)
    actuals = clean_actuals(raw_actual_records)

    # -- 2. decision selection ---------------------------------------------
    dataset = build_decision_dataset(
        date(2026, 1, 15),
        date(2026, 1, 15),
        time(9, 0),
        forecasts=forecasts,
        actuals=actuals,
    )
    assert len(dataset) == 48, "the delivery grid is always complete"
    assert int(dataset["missing_forecast"].sum()) == 44, "only the two fixture hours have data"

    # -- 3. metrics, by hand ------------------------------------------------
    # Latest vintage at or before the 09:00Z cutoff (2026-01-14) is the 08:30Z one.
    assert list(dataset["forecast_mw"][:2]) == [13100.0, 13100.0]
    assert list(dataset["forecast_mw"][2:4]) == [13400.0, 13400.0]
    assert dataset["forecast_mw"][4:].isna().all()
    assert list(dataset["actual_mw"][:2]) == [10400.0, 10600.0]
    # E = F - A, and a revision never counts as a second observation.
    assert list(dataset["error_mw"][:2]) == [2700.0, 2500.0]
    assert dataset["error_mw"][2:].isna().all()
    assert dataset["horizon_hours"].iloc[0] == pytest.approx(15.5)
    assert dataset["forecast_age_hours"].iloc[0] == pytest.approx(0.5)
    scored = summary(dataset)
    assert scored["n"] == 2, "two half-hours carry both a forecast and an actual"
    assert scored["bias_mw"] == pytest.approx((2700.0 + 2500.0) / 2)

    # -- 4. the live API, fed those fixtures --------------------------------
    monkeypatch.setattr(forecast_router, "get_decision_dataset", lambda cutoff: dataset)
    client = TestClient(create_app())
    response = client.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"})
    assert response.status_code == 200
    body = response.json()

    assert_shape(body, "DecisionResponse", fields)
    assert_shape(body["calibration"], "CalibrationInfo", fields)
    assert_shape(body["dailyEnergy"], "DailyEnergy", fields)
    assert len(body["rows"]) == 48
    for row in body["rows"]:
        assert_shape(row, "DecisionRow", fields)

    # The numbers survive the HTTP hop unchanged.
    assert body["rows"][0]["forecastMw"] == 13100.0
    assert body["rows"][0]["errorMw"] == 2700.0
    assert body["rows"][0]["forecastMwh"] == pytest.approx(6550.0)
    assert body["rows"][2]["flag"] == "missingActual"
    assert body["rows"][4]["flag"] == "missingForecast"
    assert body["counts"]["intervalsExpected"] == 48
    assert body["counts"]["intervalsWithForecast"] == 4
    assert body["counts"]["intervalsWithActual"] == 2
    assert body["counts"]["nForecastIntervals"] == 2
    # Energy is MWh = MW * 0.5, and the total is flagged partial, never padded.
    assert body["dailyEnergy"]["energyMwh"] == pytest.approx(26500.0)
    assert body["dailyEnergy"]["partial"] is True
    assert body["dailyEnergy"]["unavailable"] is False

    # Too little history for a strict decision-time calibration: the bound is
    # null and the response says why, rather than inventing a number.
    assert body["calibrationMode"] == "decision_time"
    assert body["calibration"]["available"] is False
    assert body["calibration"]["boundsMw"] is None
    assert body["calibration"]["reason"]
    assert body["rows"][0]["lowerBoundMw"] is None

    # -- 5. the same contract against the real snapshot, when it exists -----
    if not (PROCESSED_FORECAST_PATH.exists() and PROCESSED_ACTUALS_PATH.exists()):
        return

    live = TestClient(create_app())
    assert_shape(live.get("/api/health").json(), "HealthResponse", fields)
    assert_shape(live.get("/api/meta").json(), "MetaResponse", fields)
    assert_shape(
        live.get("/api/forecast/vintages", params={"delivery_date": "2026-01-15"}).json(),
        "VintagesResponse",
        fields,
    )
    assert_shape(live.get("/api/accuracy/summary").json(), "AccuracySummaryResponse", fields)
    assert_shape(live.get("/api/accuracy/daily").json(), "AccuracySeriesResponse", fields)
    assert_shape(live.get("/api/accuracy/by-hour").json(), "AccuracySeriesResponse", fields)
    assert_shape(
        live.get("/api/accuracy/distribution").json(), "AccuracyDistributionResponse", fields
    )
    by_horizon = live.get("/api/accuracy/by-horizon").json()
    assert_shape(by_horizon, "AccuracyByHorizonResponse", fields)
    for bucket in by_horizon["buckets"]:
        assert_shape(bucket, "HorizonBucket", fields)

    decision = live.get("/api/forecast/decision", params={"delivery_date": "2026-01-15"}).json()
    assert_shape(decision, "DecisionResponse", fields)
    vintages = live.get("/api/forecast/vintages", params={"delivery_date": "2026-01-15"}).json()
    for interval in vintages["intervals"]:
        assert_shape(interval, "ForecastIntervalVintages", fields)
        for vintage in interval["vintages"]:
            assert_shape(vintage, "ForecastVintage", fields)
