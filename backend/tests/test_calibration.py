"""Tests for calibration, the bound formula and out-of-sample coverage."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.services.calibration import (
    INSUFFICIENT_HISTORY,
    MODE_DECISION_TIME,
    MODE_RETROSPECTIVE,
    Calibration,
    apply_bounds,
    calibrate,
    calibrated_bounds,
    coverage_by_horizon_group,
    coverage_check,
    error_percentiles,
    lower_bound,
    upper_bound,
)

BASE_DAY = date(2026, 1, 1)


def _frame(n_days: int, error_of, horizon_of=None) -> pd.DataFrame:
    """Build a decision-time-like dataset with errors controlled by the caller."""
    rows = []
    for offset in range(n_days):
        day = BASE_DAY + timedelta(days=offset)
        for i in range(48):
            error = float(error_of(offset, i))
            rows.append(
                {
                    "delivery_date": day,
                    "start_time": pd.Timestamp(day.isoformat(), tz="UTC")
                    + pd.Timedelta(minutes=30 * i),
                    "forecast_start_time": pd.Timestamp(day.isoformat(), tz="UTC")
                    + pd.Timedelta(hours=i // 2),
                    "forecast_mw": 5000.0,
                    "actual_mw": 5000.0 - error,
                    "error_mw": error,
                    "horizon_hours": float(horizon_of(offset, i)) if horizon_of else 24.0,
                }
            )
    return pd.DataFrame(rows)


def _flat_dataset(n_days: int) -> pd.DataFrame:
    """Errors 0..47, identical each day - a known, stationary distribution."""
    return _frame(n_days, lambda offset, i: i)


def _growing_dataset(n_days: int) -> pd.DataFrame:
    """Each day's errors are ~100 MW worse than the previous day's."""
    return _frame(n_days, lambda offset, i: offset * 100 + i)


def _horizon_split_dataset(n_days: int) -> pd.DataFrame:
    """Small errors at short lead time, large errors at long lead time."""
    return _frame(
        n_days,
        lambda offset, i: (i % 24) * 4 if i < 24 else 400 + (i - 24) * 4,
        lambda offset, i: 18.0 if i < 24 else 30.0,
    )


# ---------------------------------------------------------------------------
# the bound formula and its sign convention
# ---------------------------------------------------------------------------
def test_lower_bound_uses_the_upper_error_percentile():
    # E = F - A, so A = F - E: F = 4000 with P90(E) = +800 gives 3200, not 3400.
    assert lower_bound(4000.0, 800.0) == pytest.approx(3200.0)
    assert lower_bound(4000.0, 800.0) != pytest.approx(3400.0)


def test_upper_bound_uses_the_lower_error_percentile():
    # P10(E) = -600 understates the forecast, so the upper bound rises to 4600.
    assert upper_bound(4000.0, -600.0) == pytest.approx(4600.0)


def test_bounds_are_clipped_at_zero():
    assert lower_bound(300.0, 900.0) == 0.0
    assert upper_bound(300.0, -1200.0) == pytest.approx(1500.0)


def test_lower_and_upper_bound_are_vectorised():
    series = pd.Series([4000.0, 300.0])
    assert list(lower_bound(series, 800.0)) == [3200.0, 0.0]
    assert list(upper_bound(series, -600.0)) == [4600.0, 900.0]


def test_error_percentiles_accepts_a_frame_or_a_series():
    from_frame = error_percentiles(pd.DataFrame({"error_mw": [10.0, -5.0, 20.0, -10.0]}))
    from_series = error_percentiles(pd.Series([10.0, -5.0, 20.0, -10.0]))
    assert from_frame == from_series
    assert from_frame["p90"] == pytest.approx(17.0)


def test_apply_bounds_attaches_the_calibrated_offsets():
    calibration = Calibration(
        mode=MODE_DECISION_TIME,
        available=True,
        n_days=30,
        n_intervals=1440,
        percentiles={"p90": 800.0, "p10": -600.0},
    )
    bounded = apply_bounds(pd.DataFrame({"forecast_mw": [4000.0]}), calibration)
    assert bounded["lower_bound_mw"].iloc[0] == pytest.approx(3200.0)
    assert bounded["upper_bound_mw"].iloc[0] == pytest.approx(4600.0)


def test_bounds_are_null_when_the_indicator_is_unavailable():
    unavailable = Calibration(
        mode=MODE_DECISION_TIME, available=False, n_days=2, n_intervals=96, reason="x"
    )
    assert unavailable.bounds() is None
    bounded = apply_bounds(pd.DataFrame({"forecast_mw": [4000.0]}), unavailable)
    assert pd.isna(bounded["lower_bound_mw"].iloc[0])
    assert pd.isna(bounded["upper_bound_mw"].iloc[0])


# ---------------------------------------------------------------------------
# look-ahead control
# ---------------------------------------------------------------------------
def test_strict_mode_uses_only_delivery_days_up_to_d_minus_2():
    dataset = _flat_dataset(10)
    decision_day = BASE_DAY + timedelta(days=9)
    calibration = calibrated_bounds(decision_day, dataset=dataset)

    assert calibration.strict_no_lookahead is True
    assert calibration.available
    # Days 0..7 are usable; days 8 and 9 are too recent to have been known at the
    # D-1 cutoff, so no error from a day >= D-1 is used.
    assert calibration.n_days == 8
    assert calibration.n_intervals == 8 * 48
    assert calibration.history_to == decision_day - timedelta(days=2)


def test_calibration_never_falls_back_to_future_data():
    # Plenty of *later* history exists, but nothing usable before 2026-01-20.
    dataset = pd.concat(
        [_flat_dataset(4), _frame(1, lambda o, i: i).assign(delivery_date=date(2026, 1, 25))],
        ignore_index=True,
    )
    calibration = calibrated_bounds(date(2026, 1, 25), dataset=dataset)
    assert calibration.available is False
    assert calibration.bounds() is None
    assert calibration.reason == INSUFFICIENT_HISTORY
    assert calibration.n_days == 4


def test_january_1st_without_a_december_warmup_is_unavailable():
    dataset = _flat_dataset(3)  # only 1-3 January 2026
    calibration = calibrated_bounds(date(2026, 1, 1), dataset=dataset)

    assert calibration.available is False
    assert calibration.bounds() is None
    assert calibration.reason == INSUFFICIENT_HISTORY
    assert calibration.n_days == 0


def test_retrospective_mode_uses_the_whole_month_and_is_labelled():
    dataset = _flat_dataset(10)
    calibration = calibrated_bounds(
        BASE_DAY + timedelta(days=9), strict_no_lookahead=False, dataset=dataset
    )
    assert calibration.mode == MODE_RETROSPECTIVE
    assert calibration.strict_no_lookahead is False
    assert calibration.available
    assert calibration.n_days == 10
    assert "NOT decision-time evidence" in calibration.label


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        calibrate(_flat_dataset(3), BASE_DAY, "cheating")


# ---------------------------------------------------------------------------
# out-of-sample coverage
# ---------------------------------------------------------------------------
def test_coverage_is_out_of_sample_not_in_sample():
    dataset = _growing_dataset(20)
    report = coverage_check(dataset)

    # Days 0..7 have no usable prior history and are excluded and counted.
    assert report["excluded_day_count"] == 8
    assert report["n_days"] == 12
    assert report["n_intervals"] == 12 * 48
    # Bounds are built from *older, better* days, so the drifted days breach them.
    assert report["lower_bound_coverage"] < 0.5

    # In-sample coverage on the last day, using that day's own errors, would look
    # healthy - which is exactly why it is not used as evidence.
    last_day = dataset[dataset["delivery_date"] == BASE_DAY + timedelta(days=19)]
    own_p90 = error_percentiles(last_day)["p90"]
    in_sample = (last_day["actual_mw"] >= 5000.0 - own_p90).mean()
    assert in_sample > 0.8
    assert in_sample > report["lower_bound_coverage"]


def test_coverage_reports_the_lower_bound_and_the_band():
    report = coverage_check(_flat_dataset(20))
    assert 0.0 <= report["lower_bound_coverage"] <= 1.0
    assert 0.0 <= report["band_coverage"] <= 1.0
    # The band is a subset of the lower-bound condition, so it can only be rarer.
    assert report["band_coverage"] <= report["lower_bound_coverage"] + 1e-9
    assert report["target"] == 0.9
    assert "out-of-sample" in report["note"].lower()


def test_coverage_window_limits_which_days_are_scored():
    dataset = _flat_dataset(20)
    window_from = BASE_DAY + timedelta(days=10)
    window_to = BASE_DAY + timedelta(days=12)
    report = coverage_check(dataset, eval_from=window_from, eval_to=window_to)
    assert report["n_days"] == 3
    assert report["n_intervals"] == 3 * 48


def test_coverage_on_empty_history_says_so():
    report = coverage_check(pd.DataFrame(columns=["delivery_date", "error_mw"]))
    assert report["n_intervals"] == 0
    assert report["lower_bound_coverage"] is None
    assert report["n_days"] == 0


def test_coverage_by_horizon_group_flags_material_variation():
    report = coverage_by_horizon_group(_horizon_split_dataset(20))
    groups = {group["horizon_bucket"]: group for group in report["groups"]}

    assert set(groups) == {"0-24h", "30-36h"}
    # The pooled P90 (~476 MW, driven by the long-horizon errors) sits just
    # inside the long-horizon error range 400..492 (step 4): the 20 errors
    # <= 476 are covered and the 4 above it are not.
    assert groups["0-24h"]["lower_bound_coverage"] == pytest.approx(1.0)
    assert groups["30-36h"]["lower_bound_coverage"] == pytest.approx(20 / 24)
    assert report["material_variation"] is True
    assert report["coverage_spread"] > 0.05
    assert "pooled" in report["note"]


def test_coverage_by_horizon_group_does_not_flag_a_uniform_group():
    # One horizon everywhere -> a single group, no variation to report.
    report = coverage_by_horizon_group(_flat_dataset(20))
    assert len(report["groups"]) == 1
    assert report["material_variation"] is False
    assert report["coverage_spread"] == 0.0
