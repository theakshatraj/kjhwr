"""Tests for decision-time forecast selection."""

from __future__ import annotations

from datetime import date, time

import pandas as pd
import pytest

from app.services.data_store import clean_actuals, clean_forecasts
from app.services.decision_forecast import (
    DECISION_COLUMNS,
    build_decision_dataset,
    dataset_counts,
    delivery_half_hours,
    select_decision_forecasts,
)

DELIVERY_DAY = date(2026, 1, 15)


@pytest.fixture
def forecasts(raw_forecast_records):
    return clean_forecasts(raw_forecast_records)


@pytest.fixture
def actuals(raw_actual_records):
    return clean_actuals(raw_actual_records)


def test_one_row_per_delivery_half_hour(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY)
    assert len(frame) == 48
    assert len(delivery_half_hours(DELIVERY_DAY)) == 48
    assert list(frame.columns) == DECISION_COLUMNS


def test_latest_vintage_before_the_cutoff_is_selected(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY)
    first = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")].iloc[0]
    # 08:30 is the latest issue <= 09:00 cutoff on 2026-01-14.
    assert first["publish_time"] == pd.Timestamp("2026-01-14T08:30:00Z")
    assert first["forecast_mw"] == 13100


def test_earlier_cutoff_excludes_later_versions(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY, cutoff=time(7, 0))
    first = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")].iloc[0]
    assert first["publish_time"] == pd.Timestamp("2026-01-14T05:30:00Z")
    assert first["forecast_mw"] == 12500


def test_cutoff_boundary_includes_the_exact_instant_and_excludes_one_second_later():
    records = [
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T09:00:00Z",  # exactly at the cutoff
            "startTime": "2026-01-15T00:00:00Z",
            "generation": 12000,
        },
        {
            "dataset": "WINDFOR",
            "publishTime": "2026-01-14T09:00:01Z",  # one second after
            "startTime": "2026-01-15T01:00:00Z",
            "generation": 13000,
        },
    ]
    frame = select_decision_forecasts(
        clean_forecasts(records), clean_actuals([]), DELIVERY_DAY
    )

    on_boundary = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")].iloc[0]
    after_boundary = frame[frame["start_time"] == pd.Timestamp("2026-01-15T01:00:00Z")].iloc[0]

    assert on_boundary["forecast_mw"] == 12000
    assert on_boundary["missing_forecast"] == False  # noqa: E712 - numpy bool from pandas
    assert pd.isna(after_boundary["forecast_mw"])
    assert after_boundary["missing_forecast"]


def test_missing_forecast_slots_are_flagged_not_dropped(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY)
    missing = frame[frame["missing_forecast"]]

    assert len(frame) == 48, "the delivery grid is never truncated"
    assert len(missing) == 44, "only two hourly intervals (4 slots) have a forecast"
    assert missing["forecast_mw"].isna().all()
    assert missing["error_mw"].isna().all()
    # Only the four covered slots are unflagged.
    assert int((~frame["missing_forecast"]).sum()) == 4


def test_hourly_value_is_applied_to_both_settlement_half_hours(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY)
    hour = frame[frame["forecast_start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")]
    assert len(hour) == 2, "one hourly value covers exactly two settlement half-hours"
    assert set(hour["forecast_mw"]) == {13100}
    assert hour["horizon_hours"].nunique() == 1, "both half-hours share one horizon"


def test_horizon_and_age_are_distinct_and_correct(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY)
    first = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")].iloc[0]
    # start 2026-01-15T00:00 - publish 2026-01-14T08:30 = 15.5 h ahead
    assert first["horizon_hours"] == pytest.approx(15.5)
    # cutoff 2026-01-14T09:00 - publish 2026-01-14T08:30 = 0.5 h old at decision time
    assert first["forecast_age_hours"] == pytest.approx(0.5)
    assert first["horizon_hours"] != first["forecast_age_hours"]


def test_error_uses_forecast_minus_actual(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, DELIVERY_DAY)
    first = frame[frame["start_time"] == pd.Timestamp("2026-01-15T00:00:00Z")].iloc[0]
    assert first["actual_mw"] == 10400  # latest FUELHH revision wins
    assert first["error_mw"] == pytest.approx(13100 - 10400)


def test_dst_days_have_46_and_50_half_hours():
    assert len(delivery_half_hours(date(2026, 3, 29))) == 46  # clocks go forward
    assert len(delivery_half_hours(date(2026, 10, 25))) == 50  # clocks go back


def test_a_dst_delivery_day_still_produces_a_complete_grid(forecasts, actuals):
    frame = select_decision_forecasts(forecasts, actuals, date(2026, 3, 29))
    assert len(frame) == 46


def test_counts_report_half_hours_and_unique_intervals(forecasts, actuals):
    dataset = build_decision_dataset(
        DELIVERY_DAY, DELIVERY_DAY, forecasts=forecasts, actuals=actuals
    )
    counts = dataset_counts(dataset)
    # Two scored half-hours (00:00, 00:30) from one hourly interval (00:00).
    assert counts["n_half_hours"] == 2
    assert counts["n_forecast_intervals"] == 1
    assert counts["n_days"] == 1


def test_build_decision_dataset_covers_an_inclusive_date_range(forecasts, actuals):
    dataset = build_decision_dataset(
        DELIVERY_DAY, date(2026, 1, 16), forecasts=forecasts, actuals=actuals
    )
    assert sorted(dataset["delivery_date"].unique()) == [DELIVERY_DAY, date(2026, 1, 16)]
    assert len(dataset) == 96
