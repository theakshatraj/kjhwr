"""Pydantic response models for the public API.

One convention across the whole surface: **every JSON key in an ``/api``
response is camelCase** (``forecastMw``, ``energyMwh``), while the Python
attributes stay snake_case. Declared fields get that from Pydantic's alias
generator (which also makes the OpenAPI schema show the real camelCase names).

Dynamic analytics blocks - percentiles, histograms, coverage reports - are
``dict[str, Any]`` and therefore invisible to the alias generator, so the
routers pass them through :func:`camelize` before building the model. That keeps
one rule with no exceptions, rather than camelCase at the top level and
snake_case underneath.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def to_camel(name: str) -> str:
    """``forecast_mw`` -> ``forecastMw``.

    Idempotent: a name with no underscore (already camelCase, or ``p90``) is
    returned unchanged, so a payload can be camelised more than once safely.
    """
    head, *rest = name.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest if word)


def camelize(value: Any) -> Any:
    """Recursively camelCase the keys of dicts, including dicts inside lists."""
    if isinstance(value, dict):
        return {to_camel(str(key)): camelize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [camelize(item) for item in value]
    return value


class ApiModel(BaseModel):
    """Base for every response model: snake_case in Python, camelCase in JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# orientational
# ---------------------------------------------------------------------------
class HealthOut(ApiModel):
    status: str
    data_available: bool


class MetaOut(ApiModel):
    delivery_month: dict[str, str]
    default_cutoff_local_time: str
    cutoff_note: str
    calibration_modes: list[str]
    min_calibration: dict[str, int]
    calibration_warmup: dict[str, str] = Field(
        description="extra history before the delivery month, used to seed calibration"
    )
    resolution: dict[str, Any]
    window: dict[str, str]
    counts: dict[str, int]
    horizon_range_hours: dict[str, float | None]
    data_available: bool
    snapshot_notice: str
    attribution: str
    known_deviations: list[str]
    provenance: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# decision view
# ---------------------------------------------------------------------------
class DecisionRow(ApiModel):
    start_time: datetime = Field(description="delivery settlement half-hour (UTC)")
    start_time_local: str = Field(description="same slot in Europe/London")
    forecast_start_time: datetime = Field(description="hourly WINDFOR interval used (UTC)")
    forecast_mw: float | None
    publish_time: datetime | None
    horizon_hours: float | None = Field(description="forecast_start_time - publish_time")
    forecast_age_hours: float | None = Field(description="cutoffTime - publish_time")
    actual_mw: float | None
    error_mw: float | None = Field(description="F - A; positive = overestimate")
    lower_bound_mw: float | None = Field(
        default=None, description="max(0, F - P90(E)); null when calibration is unavailable"
    )
    upper_bound_mw: float | None
    forecast_mwh: float | None = Field(description="forecast_mw * 0.5")
    flag: str | None = Field(
        default=None, description="'missingForecast' | 'missingActual' | null"
    )


class CalibrationInfo(ApiModel):
    mode: str
    label: str = Field(description="mode in words; retrospective is explicitly not evidence")
    strict_no_lookahead: bool = Field(description="true when only delivery days <= D-2 are used")
    available: bool
    n_days: int
    n_intervals: int
    warmup_days: int
    history_from: str | None = None
    history_to: str | None = None
    percentiles_mw: dict[str, float] = Field(default_factory=dict)
    bounds_mw: dict[str, float] | None = Field(
        default=None,
        description="P90(E)/P10(E) offsets, or null when the indicator is unavailable",
    )
    pooled: bool = Field(
        default=True, description="one error distribution pooled over all half-hours"
    )
    pooled_note: str = Field(default="", description="pooled-calibration limitation")
    reason: str | None = Field(
        default=None, description="why the indicator is unavailable, e.g. insufficient history"
    )


class DailyEnergy(ApiModel):
    energy_mwh: float | None = Field(
        default=None, description="sum of forecast MW over half-hours, times 0.5"
    )
    partial: bool = Field(description="true when some half-hours have no forecast")
    unavailable: bool = Field(description="true when no interval had a forecast at all")
    intervals_with_forecast: int
    intervals_expected: int
    reason: str | None = Field(default=None, description="set when unavailable")


class DecisionResponse(ApiModel):
    delivery_date: str
    cutoff_local_time: str
    cutoff_utc: datetime
    cutoff_label: str = "assumed decision cutoff"
    calibration_mode: str = Field(description="mirror of calibration.mode, for the headline")
    calibration_n: int = Field(
        description="mirror of calibration.nIntervals: the honest calibration sample size"
    )
    calibration: CalibrationInfo
    counts: dict[str, int]
    daily_energy: DailyEnergy
    rows: list[DecisionRow]


# ---------------------------------------------------------------------------
# accuracy view
# ---------------------------------------------------------------------------
class AccuracySummary(ApiModel):
    window: dict[str, str]
    cutoff_local_time: str
    dataset: str
    counts: dict[str, int]
    decision_time: dict[str, Any]
    native_hourly: dict[str, Any]
    coverage: dict[str, Any]
    coverage_by_horizon: dict[str, Any]
    calibration: CalibrationInfo


class AccuracySeries(ApiModel):
    window: dict[str, str]
    counts: dict[str, int]
    series: list[dict[str, Any]]


class AccuracyDistribution(ApiModel):
    window: dict[str, str]
    counts: dict[str, int]
    histogram: dict[str, Any]
    absolute_error_percentiles_mw: dict[str, float]


class HorizonBucket(ApiModel):
    horizon_bucket: str
    record_count: int = Field(description="rows in the bucket (vintages, correlated)")
    unique_interval_count: int = Field(description="distinct forecast intervals - the honest n")
    metrics: dict[str, Any]


class AccuracyByHorizon(ApiModel):
    dataset: str
    note: str
    total_records: int
    excluded_records: int = Field(
        description="records with publishTime >= startTime (horizon <= 0), not advance predictions"
    )
    excluded_horizon_range_hours: dict[str, float] | None = None
    horizon_inconsistent_records: int = 0
    observed_horizon_hours: dict[str, Any] = Field(default_factory=dict)
    buckets: list[HorizonBucket]


# ---------------------------------------------------------------------------
# all-vintages view (lead-time comparison per delivery day)
# ---------------------------------------------------------------------------
class ForecastVintage(ApiModel):
    publish_time: datetime
    forecast_mw: float | None
    horizon_hours: float | None = Field(description="forecast_start_time - publish_time")
    forecast_age_hours: float | None = Field(description="cutoffTime - publish_time")
    selected: bool = Field(description="the vintage the client saw at the cutoff")
    predictive: bool = Field(description="horizon_hours > 0")


class ForecastIntervalVintages(ApiModel):
    forecast_start_time: datetime
    start_time_local: str
    hourly_actual_mw: float | None
    error_mw: float | None = Field(
        default=None, description="selected vintage minus hourly actual"
    )
    vintages: list[ForecastVintage]


class VintagesResponse(ApiModel):
    delivery_date: str
    cutoff_local_time: str
    cutoff_utc: datetime
    dataset: str = "all_vintages"
    counts: dict[str, int]
    intervals: list[ForecastIntervalVintages]
