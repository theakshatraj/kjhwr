"""Accuracy view: error metrics, coverage, and the lead-time comparison.

Dynamic analytics blocks (percentiles, histograms, coverage) are ``dict``s, so
the alias generator cannot reach their keys; they are passed through
:func:`camelize` here so the whole response surface is camelCase.
"""

from __future__ import annotations

from datetime import date, time

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.config import DEFAULT_CUTOFF_LOCAL_TIME
from app.routers._helpers import (
    calibration_payload,
    parse_cutoff,
    window_bounds,
)
from app.schemas import (
    AccuracyByHorizon,
    AccuracyDistribution,
    AccuracySeries,
    AccuracySummary,
    camelize,
)
from app.services.calibration import (
    CALIBRATION_MODES,
    MODE_DECISION_TIME,
    calibrated_bounds,
    coverage_by_horizon_group,
    coverage_check,
)
from app.services.decision_forecast import (
    dataset_counts,
    delivery_month_dataset,
    get_all_vintages_dataset,
    get_decision_dataset,
)
from app.services.metrics import by_horizon, by_hour_of_day, daily, error_histogram, summary

router = APIRouter(tags=["accuracy"])


def _validated(cutoff: str, mode: str) -> tuple[time, str]:
    try:
        cutoff_time = parse_cutoff(cutoff)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if mode not in CALIBRATION_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {list(CALIBRATION_MODES)}")
    return cutoff_time, mode


def _strict(mode: str) -> bool:
    return mode == MODE_DECISION_TIME


def _window_dataset(cutoff: time, days_from: date | None, days_to: date | None):
    start, end = window_bounds(days_from, days_to)
    month = delivery_month_dataset(cutoff)
    mask = (month["delivery_date"] >= start) & (month["delivery_date"] <= end)
    return month[mask], start, end


def _native_hourly_metrics(dataset):
    """Metrics at the native forecast resolution: one error per hourly interval.

    Both settlement half-hours under an hour carry the same forecast value, so
    they are collapsed to a single observation (forecast vs mean actual) before
    scoring. This is the sample that is actually independent.
    """
    if dataset.empty:
        return {"n": 0, "note": "no data"}
    grouped = dataset.dropna(subset=["forecast_mw", "actual_mw"]).groupby(
        ["delivery_date", "forecast_start_time"], sort=True
    )
    scored = pd.DataFrame(
        {"forecast_mw": grouped["forecast_mw"].first(), "actual_mw": grouped["actual_mw"].mean()}
    )
    metrics = summary(scored)
    metrics["note"] = (
        "Native hourly resolution: one observation per forecast interval, actual averaged "
        "over the two constituent half-hours. This is the independent sample."
    )
    return metrics


@router.get("/accuracy/summary", response_model=AccuracySummary)
def accuracy_summary(
    days_from: date | None = Query(default=None, alias="from"),
    days_to: date | None = Query(default=None, alias="to"),
    cutoff: str = Query(default=DEFAULT_CUTOFF_LOCAL_TIME),
    mode: str = Query(default=MODE_DECISION_TIME),
) -> AccuracySummary:
    cutoff_time, mode = _validated(cutoff, mode)
    dataset, start, end = _window_dataset(cutoff_time, days_from, days_to)

    decision_time = summary(dataset)
    decision_time.update(dataset_counts(dataset))

    # Coverage is validated out of sample; the history includes the December
    # warm-up so early-January days are not starved of prior data.
    history = get_decision_dataset(cutoff_time)
    coverage = coverage_check(
        history, cutoff_time, _strict(mode), eval_from=start, eval_to=end
    )
    by_horizon_coverage = coverage_by_horizon_group(
        history, cutoff_time, _strict(mode), eval_from=start, eval_to=end
    )

    # Representative calibration for the end of the window (mode still applies).
    calibration = calibrated_bounds(end, cutoff_time, _strict(mode), dataset=history)

    return AccuracySummary(
        window={"from": start.isoformat(), "to": end.isoformat()},
        cutoff_local_time=cutoff_time.strftime("%H:%M"),
        dataset="decision_time",
        counts=camelize(dataset_counts(dataset)),
        decision_time=camelize(decision_time),
        native_hourly=camelize(_native_hourly_metrics(dataset)),
        coverage=camelize(coverage),
        coverage_by_horizon=camelize(by_horizon_coverage),
        calibration=calibration_payload(calibration),
    )


@router.get("/accuracy/daily", response_model=AccuracySeries)
def accuracy_daily(
    days_from: date | None = Query(default=None, alias="from"),
    days_to: date | None = Query(default=None, alias="to"),
    cutoff: str = Query(default=DEFAULT_CUTOFF_LOCAL_TIME),
    mode: str = Query(default=MODE_DECISION_TIME),
) -> AccuracySeries:
    cutoff_time, mode = _validated(cutoff, mode)
    dataset, start, end = _window_dataset(cutoff_time, days_from, days_to)
    return AccuracySeries(
        window={"from": start.isoformat(), "to": end.isoformat()},
        counts=camelize(dataset_counts(dataset)),
        series=camelize(daily(dataset)),
    )


@router.get("/accuracy/by-hour", response_model=AccuracySeries)
def accuracy_by_hour(
    days_from: date | None = Query(default=None, alias="from"),
    days_to: date | None = Query(default=None, alias="to"),
    cutoff: str = Query(default=DEFAULT_CUTOFF_LOCAL_TIME),
    mode: str = Query(default=MODE_DECISION_TIME),
) -> AccuracySeries:
    cutoff_time, mode = _validated(cutoff, mode)
    dataset, start, end = _window_dataset(cutoff_time, days_from, days_to)
    return AccuracySeries(
        window={"from": start.isoformat(), "to": end.isoformat()},
        counts=camelize(dataset_counts(dataset)),
        series=camelize(by_hour_of_day(dataset)),
    )


@router.get("/accuracy/distribution", response_model=AccuracyDistribution)
def accuracy_distribution(
    days_from: date | None = Query(default=None, alias="from"),
    days_to: date | None = Query(default=None, alias="to"),
    cutoff: str = Query(default=DEFAULT_CUTOFF_LOCAL_TIME),
    mode: str = Query(default=MODE_DECISION_TIME),
) -> AccuracyDistribution:
    cutoff_time, mode = _validated(cutoff, mode)
    dataset, start, end = _window_dataset(cutoff_time, days_from, days_to)
    return AccuracyDistribution(
        window={"from": start.isoformat(), "to": end.isoformat()},
        counts=camelize(dataset_counts(dataset)),
        histogram=camelize(error_histogram(dataset)),
        absolute_error_percentiles_mw=camelize(
            summary(dataset)["absolute_error_percentiles_mw"]
        ),
    )


@router.get("/accuracy/by-horizon", response_model=AccuracyByHorizon)
def accuracy_by_horizon() -> AccuracyByHorizon:
    """Lead-time comparison across *all* forecast vintages (hourly resolution).

    Kept separate from the decision-time headline on purpose: here several
    forecasts share one target hour and are correlated, so both the record count
    and the distinct-interval count are reported. Records published at or after
    their target time (``horizon_hours <= 0``) are excluded by ``metrics.by_horizon``
    and counted, rather than being dropped silently.
    """
    analysis = by_horizon(get_all_vintages_dataset())
    return AccuracyByHorizon(
        dataset="all_vintages",
        note=analysis["note"],
        total_records=analysis["total_records"],
        excluded_records=analysis["excluded_records"],
        excluded_horizon_range_hours=camelize(analysis["excluded_horizon_range_hours"]),
        horizon_inconsistent_records=analysis["horizon_inconsistent_records"],
        observed_horizon_hours=camelize(analysis["observed_horizon_hours"]),
        buckets=camelize(analysis["buckets"]),
    )
