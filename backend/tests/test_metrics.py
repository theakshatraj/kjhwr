"""Tests for the error metrics (pure functions, hand-computed fixtures)."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.metrics import (
    MWH_PER_HALF_HOUR,
    absolute_error_percentiles,
    by_horizon,
    by_hour_of_day,
    daily,
    daily_energy_mwh,
    error_histogram,
    horizon_bucket,
    signed_error_percentiles,
    summary,
)

FORECAST = [110.0, 95.0, 120.0, 90.0]
ACTUAL = [100.0, 100.0, 100.0, 100.0]
# errors E = F - A -> [10, -5, 20, -10]


def scored(forecast=FORECAST, actual=ACTUAL, **extra) -> pd.DataFrame:
    return pd.DataFrame({"forecast_mw": forecast, "actual_mw": actual, **extra})


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
def test_summary_reports_bias_mae_rmse_and_mae_percent():
    metrics = summary(scored())
    assert metrics["n"] == 4
    assert metrics["bias_mw"] == pytest.approx(3.75)
    assert metrics["mae_mw"] == pytest.approx(11.25)
    assert metrics["rmse_mw"] == pytest.approx(12.5)
    assert metrics["mean_actual_mw"] == pytest.approx(100.0)
    assert metrics["mae_pct_of_mean_actual"] == pytest.approx(11.25)


def test_signed_and_absolute_percentiles_are_named_separately():
    metrics = summary(scored())
    signed = metrics["signed_error_percentiles_mw"]
    absolute = metrics["absolute_error_percentiles_mw"]

    assert set(signed) == {"p5", "p10", "p50", "p90", "p95"}
    assert set(absolute) == {"p50", "p90"}
    # Signed p10 is negative; the absolute family can never be negative.
    assert signed["p10"] == pytest.approx(-8.5)
    assert signed["p90"] == pytest.approx(17.0)
    assert absolute["p50"] == pytest.approx(10.0)
    assert absolute["p90"] == pytest.approx(17.0)
    assert all(v >= 0 for v in absolute.values())


def test_summary_recomputes_the_error_and_ignores_a_supplied_error_column():
    # A stale/incorrect error_mw column must not leak into the metrics.
    metrics = summary(scored(error_mw=[999.0, 999.0, 999.0, 999.0]))
    assert metrics["bias_mw"] == pytest.approx(3.75)


def test_percentiles_ignore_missing_values():
    assert signed_error_percentiles([10.0, None, 20.0])["p50"] == pytest.approx(15.0)
    assert absolute_error_percentiles([-10.0, None, 20.0])["p50"] == pytest.approx(15.0)


def test_summary_on_empty_input_is_null_not_zero():
    metrics = summary(pd.DataFrame(columns=["forecast_mw", "actual_mw"]))
    assert metrics["n"] == 0
    assert metrics["bias_mw"] is None
    assert metrics["mae_mw"] is None
    assert metrics["signed_error_percentiles_mw"] == {}


def test_unpaired_values_are_dropped_before_scoring():
    metrics = summary(scored([10.0, float("nan")], [10.0, 10.0]))
    assert metrics["n"] == 1
    assert metrics["bias_mw"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# groupings
# ---------------------------------------------------------------------------
def test_by_hour_of_day_covers_every_london_hour():
    dataset = pd.DataFrame(
        {
            "forecast_mw": [100.0] * 24,
            "actual_mw": [100.0] * 24,
            "start_time": pd.to_datetime(
                [f"2026-01-15T{h:02d}:00:00Z" for h in range(24)], utc=True
            ),
        }
    )
    series = by_hour_of_day(dataset)
    assert [row["hour"] for row in series] == list(range(24))
    assert all(row["n"] == 1 for row in series)


def test_daily_groups_by_delivery_date():
    dataset = scored(
        delivery_date=[pd.Timestamp("2026-01-01").date()] * 2
        + [pd.Timestamp("2026-01-02").date()] * 2
    )
    series = daily(dataset)
    assert [row["delivery_date"] for row in series] == ["2026-01-01", "2026-01-02"]
    assert [row["n"] for row in series] == [2, 2]


def test_error_histogram_returns_bins_and_counts():
    histogram = error_histogram(scored(), bins=4)
    assert histogram["n"] == 4
    assert len(histogram["counts"]) == 4
    assert len(histogram["bin_edges_mw"]) == 5
    assert sum(histogram["counts"]) == 4


# ---------------------------------------------------------------------------
# energy
# ---------------------------------------------------------------------------
def test_mwh_per_half_hour_is_mw_times_zero_point_five():
    energy = daily_energy_mwh(scored([4000.0], [3900.0]))
    assert MWH_PER_HALF_HOUR == 0.5
    assert energy["energy_mwh"] == pytest.approx(2000.0)
    assert energy["valid_intervals"] == 1
    assert energy["expected_intervals"] == 1
    assert energy["partial"] is False
    assert energy["unavailable"] is False


def test_daily_energy_flags_one_missing_interval_as_partial():
    forecast = [4000.0] * 48
    forecast[7] = float("nan")
    energy = daily_energy_mwh(scored(forecast, [4000.0] * 48))

    assert energy["expected_intervals"] == 48
    assert energy["valid_intervals"] == 47
    assert energy["partial"] is True
    assert energy["unavailable"] is False
    # The missing slot contributes nothing - it is NOT completed with a zero.
    assert energy["energy_mwh"] == pytest.approx(47 * 4000.0 * 0.5)


def test_daily_energy_is_unavailable_when_no_interval_has_a_forecast():
    energy = daily_energy_mwh(scored([float("nan")] * 48, [4000.0] * 48))
    assert energy["energy_mwh"] is None
    assert energy["valid_intervals"] == 0
    assert energy["expected_intervals"] == 48
    assert energy["partial"] is True
    assert energy["unavailable"] is True


# ---------------------------------------------------------------------------
# horizon analysis
# ---------------------------------------------------------------------------
def _vintages(rows: list[tuple[str, str, float, float]]) -> pd.DataFrame:
    """(start_time, publish_time, forecast_mw, hourly_actual_mw) -> all-vintages frame."""
    frame = pd.DataFrame(
        [
            {
                "start_time": pd.Timestamp(start, tz="UTC"),
                "publish_time": pd.Timestamp(publish, tz="UTC"),
                "generation_mw": forecast,
                "hourly_actual_mw": actual,
            }
            for start, publish, forecast, actual in rows
        ]
    )
    frame["horizon_hours"] = (
        frame["start_time"] - frame["publish_time"]
    ).dt.total_seconds() / 3600.0
    return frame


VINTAGE_ROWS = [
    # two vintages of the same target hour, both 24-30 h ahead
    ("2026-01-15T00:00:00Z", "2026-01-14T00:00:00Z", 1000.0, 900.0),  # 24.0 h
    ("2026-01-15T00:00:00Z", "2026-01-13T20:00:00Z", 1100.0, 900.0),  # 28.0 h
    # one target hour with an 0-24 h lead time
    ("2026-01-16T00:00:00Z", "2026-01-15T02:00:00Z", 1200.0, 1000.0),  # 22.0 h
    # published exactly at the target time -> not an advance prediction
    ("2026-01-16T12:00:00Z", "2026-01-16T12:00:00Z", 1300.0, 1000.0),  # 0.0 h
    # published after the target time -> also not an advance prediction
    ("2026-01-16T18:00:00Z", "2026-01-17T00:00:00Z", 1400.0, 1000.0),  # -6.0 h
]


def test_horizon_bucket_labels():
    assert horizon_bucket(18.0) == "0-24h"
    assert horizon_bucket(24.0) == "24-30h"
    assert horizon_bucket(28.0) == "24-30h"
    assert horizon_bucket(50.0) == "48h+"
    assert horizon_bucket(None) is None
    assert horizon_bucket(-1.0) is None


def test_by_horizon_reports_records_and_unique_intervals_which_differ():
    analysis = by_horizon(_vintages(VINTAGE_ROWS))
    buckets = {bucket["horizon_bucket"]: bucket for bucket in analysis["buckets"]}

    assert set(buckets) == {"0-24h", "24-30h"}
    # Two vintages of the *same* target hour - records outnumber intervals.
    assert buckets["24-30h"]["record_count"] == 2
    assert buckets["24-30h"]["unique_interval_count"] == 1
    assert buckets["24-30h"]["metrics"]["n"] == 2
    # The honest sample size, not the record count.
    assert buckets["0-24h"]["record_count"] == 1
    assert buckets["0-24h"]["unique_interval_count"] == 1


def test_by_horizon_excludes_and_counts_records_published_after_their_target():
    analysis = by_horizon(_vintages(VINTAGE_ROWS))
    assert analysis["total_records"] == 5
    assert analysis["excluded_records"] == 2
    assert analysis["excluded_horizon_range_hours"] == {"min": -6.0, "max": 0.0}
    # The excluded records are reported, not silently removed.
    assert analysis["horizon_inconsistent_records"] == 0
    assert "excluded" in analysis["note"].lower()


def test_by_horizon_validates_the_horizon_column():
    frame = _vintages(VINTAGE_ROWS)
    # Corrupt the stated horizon of one record; the mismatch must be reported.
    frame.loc[0, "horizon_hours"] = 999.0
    analysis = by_horizon(frame)
    assert analysis["horizon_inconsistent_records"] == 1
