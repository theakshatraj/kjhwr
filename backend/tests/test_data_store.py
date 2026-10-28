"""Tests for the cleaning logic in ``app.services.data_store``."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.config import decision_cutoff_utc
from app.services.data_store import (
    FORECAST_INTERVAL_MINUTES,
    PROCESSED_ACTUALS_CSV,
    PROCESSED_FORECAST_CSV,
    SETTLEMENT_INTERVAL_MINUTES,
    _read_snapshot,
    clean_actuals,
    clean_forecasts,
    expected_half_hours,
    forecast_hour_start,
    settlement_slots_for_forecast_hour,
)


# ---------------------------------------------------------------------------
# forecasts
# ---------------------------------------------------------------------------
def test_forecasts_keep_every_vintage_of_the_same_start_time(raw_forecast_records):
    frame = clean_forecasts(raw_forecast_records)

    same_target = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")]
    assert len(same_target) == 3, "historical publish versions must not be collapsed"
    assert list(same_target["generation_mw"]) == [12000, 12500, 13100]
    assert same_target["publish_time"].is_monotonic_increasing


def test_forecasts_derive_horizon_hours(raw_forecast_records):
    frame = clean_forecasts(raw_forecast_records)
    first = frame[frame["publish_time"] == pd.Timestamp("2026-01-14T02:30:00Z")].iloc[0]
    # 2026-01-14T02:30 -> 2026-01-15T00:00 is 21.5 hours
    assert first["horizon_hours"] == pytest.approx(21.5)


def test_forecasts_drop_exact_duplicates_and_count_them(raw_forecast_records):
    duplicated = raw_forecast_records + [raw_forecast_records[0]]
    frame = clean_forecasts(duplicated)
    assert len(frame) == len(raw_forecast_records)
    assert frame.attrs["stats"]["dropped_duplicates"] == 1


def test_forecasts_drop_null_generation_without_hiding_it(raw_forecast_records):
    records = raw_forecast_records + [
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T09:30:00Z",
            "startTime": "2026-01-15T02:00:00Z",
            "generation": None,
        }
    ]
    frame = clean_forecasts(records)
    assert len(frame) == len(raw_forecast_records)
    assert frame.attrs["stats"]["dropped_null_generation"] == 1


def test_forecasts_raise_when_a_key_timestamp_is_null(raw_forecast_records):
    broken = raw_forecast_records + [
        {
            "dataset": "WINDFOR",
            "publishTime": None,
            "startTime": "2026-01-15T03:00:00Z",
            "generation": 9000,
        }
    ]
    with pytest.raises(ValueError, match="null key column"):
        clean_forecasts(broken)


def test_forecasts_empty_input_returns_empty_frame():
    frame = clean_forecasts([])
    assert frame.empty
    assert list(frame.columns) == ["start_time", "publish_time", "generation_mw", "horizon_hours"]


# ---------------------------------------------------------------------------
# actuals
# ---------------------------------------------------------------------------
def test_actuals_keep_only_the_latest_revision(raw_actual_records):
    frame = clean_actuals(raw_actual_records)

    assert len(frame) == 2
    first = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")].iloc[0]
    assert first["generation_mw"] == 10400, "the later publishTime must win"
    assert frame.attrs["stats"]["dropped_revisions"] == 1


def test_actuals_are_sorted_by_start_time(raw_actual_records):
    frame = clean_actuals(list(reversed(raw_actual_records)))
    assert frame["start_time"].is_monotonic_increasing


def test_actuals_raise_when_start_time_is_null(raw_actual_records):
    broken = raw_actual_records + [
        {
            "dataset": "FUELHH",
            "publishTime": "2026-01-15T01:30:00Z",
            "startTime": None,
            "settlementDate": "2026-01-15",
            "settlementPeriod": 3,
            "fuelType": "WIND",
            "generation": 1,
        }
    ]
    with pytest.raises(ValueError, match="null key column"):
        clean_actuals(broken)


# ---------------------------------------------------------------------------
# expected interval grid
# ---------------------------------------------------------------------------
def test_expected_half_hours_counts_a_normal_day_and_the_window():
    assert len(expected_half_hours("2026-01-15", "2026-01-15")) == 48
    assert len(expected_half_hours("2025-12-01", "2026-01-31")) == 62 * 48


def test_expected_half_hours_handles_dst_days():
    # UK clocks go forward on 2026-03-29 (46 half-hours) and back on 2026-10-25 (50).
    assert len(expected_half_hours("2026-03-29", "2026-03-29")) == 46
    assert len(expected_half_hours("2026-10-25", "2026-10-25")) == 50


def test_expected_half_hours_is_utc_and_contiguous():
    index = expected_half_hours("2026-03-29", "2026-03-29")
    assert str(index.tz) == "UTC"
    assert (index.to_series().diff().dropna() == pd.Timedelta(minutes=30)).all()


# ---------------------------------------------------------------------------
# decision cutoff
# ---------------------------------------------------------------------------
def test_decision_cutoff_is_0900_london_on_the_previous_day():
    cutoff = decision_cutoff_utc(date(2026, 1, 15))
    # January is GMT, so 09:00 London == 09:00 UTC.
    assert cutoff == pd.Timestamp("2026-01-14T09:00:00Z")
    assert cutoff.date() == date(2026, 1, 14)


def test_decision_cutoff_respects_british_summer_time():
    # 2026-07-15 delivery -> cutoff on 2026-07-14 at 09:00 BST == 08:00 UTC.
    cutoff = decision_cutoff_utc(date(2026, 7, 15))
    assert cutoff == pd.Timestamp("2026-07-14T08:00:00Z")


# ---------------------------------------------------------------------------
# resolution mapping (measured: WINDFOR hourly -> FUELHH half-hourly)
# ---------------------------------------------------------------------------
def test_measured_intervals_are_hourly_forecast_over_half_hour_settlement():
    assert FORECAST_INTERVAL_MINUTES == 60
    assert SETTLEMENT_INTERVAL_MINUTES == 30
    assert FORECAST_INTERVAL_MINUTES // SETTLEMENT_INTERVAL_MINUTES == 2


def test_forecast_hour_start_floors_a_half_hour_to_its_containing_hour():
    assert forecast_hour_start(pd.Timestamp("2026-01-15T00:00:00Z")) == pd.Timestamp(
        "2026-01-15T00:00:00Z"
    )
    assert forecast_hour_start(pd.Timestamp("2026-01-15T00:30:00Z")) == pd.Timestamp(
        "2026-01-15T00:00:00Z"
    )
    assert forecast_hour_start(pd.Timestamp("2026-01-15T13:30:00Z")) == pd.Timestamp(
        "2026-01-15T13:00:00Z"
    )


def test_each_forecast_hour_covers_exactly_two_settlement_slots():
    slots = settlement_slots_for_forecast_hour(pd.Timestamp("2026-01-15T00:00:00Z"))
    assert slots == [
        pd.Timestamp("2026-01-15T00:00:00Z"),
        pd.Timestamp("2026-01-15T00:30:00Z"),
    ]


def test_a_london_day_maps_48_settlement_slots_onto_24_forecast_hours_used_twice():
    day = expected_half_hours("2026-01-15", "2026-01-15")
    hours = {forecast_hour_start(ts) for ts in day}
    assert len(day) == 48
    assert len(hours) == 24, "one distinct hourly forecast value per hour"
    # Two settlement slots per hour == no hourly value counted as independent twice.
    usage = [sum(1 for ts in day if forecast_hour_start(ts) == h) for h in sorted(hours)]
    assert usage == [2] * 24


def test_csv_snapshot_parses_utc_timestamps_when_parquet_is_absent():
    """Vercel ships CSV, not parquet; the pathlib CSV path must be enough."""
    assert PROCESSED_FORECAST_CSV.exists()
    assert PROCESSED_ACTUALS_CSV.exists()
    missing = PROCESSED_FORECAST_CSV.parent / "does-not-exist.parquet"
    forecasts = _read_snapshot(missing, PROCESSED_FORECAST_CSV, ["start_time", "publish_time"])
    actuals = _read_snapshot(missing, PROCESSED_ACTUALS_CSV, ["start_time"])
    assert len(forecasts) == 36208
    assert len(actuals) == 2976
    assert str(forecasts["start_time"].dtype) == "datetime64[ns, UTC]"
    assert str(actuals["start_time"].dtype) == "datetime64[ns, UTC]"

