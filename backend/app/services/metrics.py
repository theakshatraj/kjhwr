"""Error metrics for the wind forecast snapshot.

Sign convention, fixed everywhere: ``E = F - A`` in MW. Positive means the
forecast *overestimated* wind. ``error_mw`` columns are always derived here, so
the convention cannot drift between callers.

Two families of percentiles are kept deliberately separate:

* **signed** error percentiles (P5..P95) - these feed the prediction bounds;
* **absolute** error percentiles (P50, P90 of ``|E|``) - "typical miss size".

Because WINDFOR is hourly and FUELHH is half-hourly, a half-hour row count
overstates the independent sample. Every grouping therefore reports both the
row count and, where the columns allow it, the distinct forecast-interval count.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from app.config import LONDON_TZ

#: Energy in one settlement half-hour of a constant MW output.
MWH_PER_HALF_HOUR = 0.5

SIGNED_PERCENTILES: tuple[int, ...] = (5, 10, 50, 90, 95)
ABSOLUTE_PERCENTILES: tuple[int, ...] = (50, 90)

#: Lead-time buckets for the horizon analyses. Derived from the observed horizon
#: distribution in the snapshot rather than picked arbitrarily: the decision-time
#: selection spans ~16.5-39.5 h (median ~28 h), and the all-vintages sample spans
#: day-ahead lead times either side of 24 h. ``horizon_distribution`` reports the
#: evidence so the choice can be re-checked against new data.
HORIZON_EDGES: tuple[float, ...] = (0.0, 24.0, 30.0, 36.0, 42.0, 48.0)


def horizon_bucket(hours: float | None, edges: Sequence[float] = HORIZON_EDGES) -> str | None:
    """Label a lead time, e.g. ``"24-30h"``. ``None`` when unknown or negative."""
    if hours is None or pd.isna(hours):
        return None
    value = float(hours)
    if value < edges[0]:
        return None
    for low, high in zip(edges, edges[1:]):
        if low <= value < high:
            return f"{_trim(low)}-{_trim(high)}h"
    return f"{_trim(edges[-1])}h+"


def _trim(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def horizon_distribution(horizons: Iterable[float]) -> dict[str, float | int | None]:
    """Observed lead-time distribution - the evidence behind ``HORIZON_EDGES``."""
    series = _clean(horizons)
    if series.empty:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}
    return {
        "n": int(len(series)),
        "min": float(series.min()),
        "p25": float(series.quantile(0.25)),
        "median": float(series.median()),
        "p75": float(series.quantile(0.75)),
        "max": float(series.max()),
    }


def _clean(values: Iterable[float]) -> pd.Series:
    series = pd.Series(list(values), dtype="float64")
    return series.dropna()


def signed_error_percentiles(
    errors: Iterable[float], probs: tuple[int, ...] = SIGNED_PERCENTILES
) -> dict[str, float]:
    """Percentiles of the signed error ``E = F - A`` (can be negative)."""
    series = _clean(errors)
    if series.empty:
        return {}
    return {f"p{p}": float(series.quantile(p / 100.0)) for p in probs}


def absolute_error_percentiles(
    errors: Iterable[float], probs: tuple[int, ...] = ABSOLUTE_PERCENTILES
) -> dict[str, float]:
    """Percentiles of ``|E|`` - the typical miss size, never negative."""
    series = _clean(errors).abs()
    if series.empty:
        return {}
    return {f"p{p}": float(series.quantile(p / 100.0)) for p in probs}


def summary(dataset: pd.DataFrame) -> dict:
    """Bias / MAE / RMSE / MAE% plus both percentile families.

    ``dataset`` needs ``forecast_mw`` and ``actual_mw`` columns; the error is
    recomputed here as ``F - A``. Rows where either side is missing are dropped
    (they are not scored as zero).
    """
    empty = {
        "n": 0,
        "bias_mw": None,
        "mae_mw": None,
        "rmse_mw": None,
        "mae_pct_of_mean_actual": None,
        "mean_actual_mw": None,
        "signed_error_percentiles_mw": {},
        "absolute_error_percentiles_mw": {},
    }
    if dataset.empty:
        return dict(empty)

    forecast = pd.to_numeric(dataset["forecast_mw"], errors="coerce")
    actual = pd.to_numeric(dataset["actual_mw"], errors="coerce")
    mask = forecast.notna() & actual.notna()
    if not mask.any():
        return dict(empty)

    error = (forecast[mask] - actual[mask]).astype("float64")
    mean_actual = float(actual[mask].mean())
    mae = float(error.abs().mean())
    return {
        "n": int(len(error)),
        "bias_mw": float(error.mean()),
        "mae_mw": mae,
        "rmse_mw": float(np.sqrt((error**2).mean())),
        # Wind sits near zero at times, so MAE is expressed against mean actual.
        "mae_pct_of_mean_actual": (mae / mean_actual * 100.0) if mean_actual else None,
        "mean_actual_mw": mean_actual,
        "signed_error_percentiles_mw": signed_error_percentiles(error),
        "absolute_error_percentiles_mw": absolute_error_percentiles(error),
    }


def by_hour_of_day(dataset: pd.DataFrame) -> list[dict]:
    """One summary per London hour of day (decision-time dataset)."""
    if dataset.empty or "start_time" not in dataset.columns:
        return []
    frame = dataset.copy()
    frame["hour"] = frame["start_time"].dt.tz_convert(LONDON_TZ).dt.hour
    rows: list[dict] = []
    for hour, chunk in frame.groupby("hour", sort=True):
        rows.append({"hour": int(hour), **summary(chunk)})
    return rows


def daily(dataset: pd.DataFrame) -> list[dict]:
    """One summary per delivery day (decision-time dataset)."""
    if dataset.empty or "delivery_date" not in dataset.columns:
        return []
    rows: list[dict] = []
    for day, chunk in dataset.groupby("delivery_date", sort=True):
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        rows.append({"delivery_date": key, **summary(chunk)})
    return rows


def error_histogram(dataset: pd.DataFrame, bins: int = 40) -> dict:
    """Histogram of the signed error, for the accuracy-view chart."""
    if dataset.empty or "forecast_mw" not in dataset.columns:
        return {"bin_edges_mw": [], "counts": [], "n": 0}
    forecast = pd.to_numeric(dataset["forecast_mw"], errors="coerce")
    actual = pd.to_numeric(dataset["actual_mw"], errors="coerce")
    error = _clean(forecast[forecast.notna() & actual.notna()] - actual[forecast.notna() & actual.notna()])
    if error.empty:
        return {"bin_edges_mw": [], "counts": [], "n": 0}
    counts, edges = np.histogram(error, bins=bins)
    return {
        "bin_edges_mw": [float(e) for e in edges],
        "counts": [int(c) for c in counts],
        "n": int(len(error)),
    }


def by_horizon(
    all_vintages_dataset: pd.DataFrame, buckets: Sequence[float] = HORIZON_EDGES
) -> dict:
    """Lead-time comparison across **all** forecast vintages, at hourly resolution.

    Validation is explicit rather than implicit:

    * ``horizon_hours`` is re-derived from ``start_time - publish_time`` and any
      row that disagrees is counted in ``horizon_inconsistent_records``;
    * records with ``publish_time >= start_time`` (``horizon_hours <= 0``) are
      not valid advance predictions. They are excluded, and the count plus the
      range of the offending horizons are reported so the timestamps can be
      investigated instead of vanishing.

    Because several vintages share one target hour and are correlated, both
    ``record_count`` and ``unique_interval_count`` are reported per bucket; the
    latter is the honest sample size.
    """
    if all_vintages_dataset.empty:
        return {
            "buckets": [],
            "total_records": 0,
            "excluded_records": 0,
            "excluded_horizon_range_hours": None,
            "horizon_inconsistent_records": 0,
            "observed_horizon_hours": horizon_distribution([]),
            "note": "no forecast vintages available",
        }

    frame = all_vintages_dataset.copy()
    recomputed = (frame["start_time"] - frame["publish_time"]).dt.total_seconds() / 3600.0
    inconsistent = int(((recomputed - frame["horizon_hours"]).abs() > 1e-6).sum())

    predictive = frame[frame["horizon_hours"] > 0].copy()
    excluded = frame[frame["horizon_hours"] <= 0]
    excluded_range = (
        {
            "min": float(excluded["horizon_hours"].min()),
            "max": float(excluded["horizon_hours"].max()),
        }
        if not excluded.empty
        else None
    )

    predictive["horizon_bucket"] = predictive["horizon_hours"].map(
        lambda h: horizon_bucket(h, buckets)
    )

    out: list[dict] = []
    for label, chunk in predictive.dropna(subset=["horizon_bucket"]).groupby(
        "horizon_bucket", sort=True
    ):
        scored = pd.DataFrame(
            {
                "forecast_mw": chunk["generation_mw"],
                "actual_mw": chunk["hourly_actual_mw"],
            }
        )
        out.append(
            {
                "horizon_bucket": str(label),
                "record_count": int(len(chunk)),
                "unique_interval_count": int(chunk["start_time"].nunique()),
                "metrics": summary(scored),
            }
        )

    return {
        "buckets": out,
        "total_records": int(len(frame)),
        "excluded_records": int(len(excluded)),
        "excluded_horizon_range_hours": excluded_range,
        "horizon_inconsistent_records": inconsistent,
        "observed_horizon_hours": horizon_distribution(predictive["horizon_hours"]),
        "note": (
            "Lead-time comparison only: several vintages share one target hour and are "
            "correlated, so unique_interval_count is the independent sample, not "
            "record_count. Excluded records carry horizon_hours <= 0 (published at or "
            "after their target time) and are not valid advance predictions."
        ),
    }


def daily_energy_mwh(dataset: pd.DataFrame) -> dict:
    """Energy total for a delivery day: ``MWh = MW * 0.5`` per half-hour.

    Only intervals that *have* a forecast contribute. If any delivery interval is
    missing its forecast the total is marked ``partial``, and if none are present
    it is ``unavailable`` (``energy_mwh`` is then ``None``). Missing generation is
    never replaced with zero to make the sum look complete.
    """
    expected_intervals = int(len(dataset))
    if expected_intervals == 0 or "forecast_mw" not in dataset.columns:
        return {
            "energy_mwh": None,
            "valid_intervals": 0,
            "expected_intervals": expected_intervals,
            "partial": True,
            "unavailable": True,
        }

    forecast = pd.to_numeric(dataset["forecast_mw"], errors="coerce")
    valid_mask = forecast.notna()
    valid_intervals = int(valid_mask.sum())
    if valid_intervals == 0:
        return {
            "energy_mwh": None,
            "valid_intervals": 0,
            "expected_intervals": expected_intervals,
            "partial": True,
            "unavailable": True,
        }

    return {
        "energy_mwh": float(forecast[valid_mask].sum() * MWH_PER_HALF_HOUR),
        "valid_intervals": valid_intervals,
        "expected_intervals": expected_intervals,
        "partial": valid_intervals < expected_intervals,
        "unavailable": False,
    }
