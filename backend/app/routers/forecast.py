"""Decision view: the forecast visible at the assumed decision cutoff.

Also exposes the *all-vintages* view, which is a deliberately separate analysis:
it shows every published version of each hourly interval, not just the one the
client saw at the cutoff.
"""

from __future__ import annotations

from datetime import date, time

from fastapi import APIRouter, HTTPException, Query

from app.config import (
    DEFAULT_CUTOFF_LOCAL_TIME,
    DELIVERY_MONTH_END,
    LONDON_TZ,
    decision_cutoff_utc,
)
from app.routers._helpers import (
    as_datetime,
    calibration_payload,
    number,
    parse_cutoff,
    require_delivery_date,
)
from app.schemas import DecisionResponse, VintagesResponse, camelize
from app.services.calibration import (
    CALIBRATION_MODES,
    MODE_DECISION_TIME,
    apply_bounds,
    calibrated_bounds,
)
from app.services.data_store import forecast_hour_start, get_snapshot
from app.services.decision_forecast import delivery_half_hours, get_decision_dataset
from app.services.metrics import daily_energy_mwh

router = APIRouter(tags=["forecast"])

NO_FORECAST_REASON = "no forecast available for any delivery interval of this day"


def _cutoff(cutoff: str) -> time:
    try:
        return parse_cutoff(cutoff)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _mode(mode: str) -> str:
    if mode not in CALIBRATION_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {list(CALIBRATION_MODES)}")
    return mode


def _flag(forecast_mw, actual_mw) -> str | None:
    if number(forecast_mw) is None:
        return "missingForecast"
    if number(actual_mw) is None:
        return "missingActual"
    return None


@router.get("/forecast/decision", response_model=DecisionResponse)
def decision_forecast(
    delivery_date: date = Query(
        default=DELIVERY_MONTH_END, description="delivery day (YYYY-MM-DD), January 2026"
    ),
    cutoff: str = Query(
        default=DEFAULT_CUTOFF_LOCAL_TIME,
        description="assumed cutoff HH:MM Europe/London, on the day before delivery",
    ),
    mode: str = Query(
        default=MODE_DECISION_TIME,
        description="decision_time (strict, default) or retrospective",
    ),
) -> DecisionResponse:
    """One row per settlement half-hour of the delivery day.

    Every slot is returned, including slots with no eligible forecast (those
    carry a null ``forecastMw`` and ``flag = missingForecast``).
    """
    day = require_delivery_date(delivery_date)
    cutoff_time = _cutoff(cutoff)
    mode = _mode(mode)

    full = get_decision_dataset(cutoff_time)
    rows_for_day = full[full["delivery_date"] == day]
    if rows_for_day.empty:
        raise HTTPException(
            status_code=404,
            detail=f"no delivery intervals for {day.isoformat()} are present in the snapshot",
        )

    calibration = calibrated_bounds(
        day, cutoff_time, mode == MODE_DECISION_TIME, dataset=full
    )
    bounded = apply_bounds(rows_for_day, calibration)

    rows = []
    for row in bounded.itertuples(index=False):
        forecast_mw = number(row.forecast_mw)
        rows.append(
            {
                "start_time": as_datetime(row.start_time),
                "start_time_local": row.start_time.tz_convert(LONDON_TZ).strftime("%H:%M"),
                "forecast_start_time": as_datetime(row.forecast_start_time),
                "forecast_mw": forecast_mw,
                "publish_time": as_datetime(row.publish_time),
                "horizon_hours": number(row.horizon_hours),
                "forecast_age_hours": number(row.forecast_age_hours),
                "actual_mw": number(row.actual_mw),
                "error_mw": number(row.error_mw),
                "lower_bound_mw": number(row.lower_bound_mw),
                "upper_bound_mw": number(row.upper_bound_mw),
                "forecast_mwh": None if forecast_mw is None else forecast_mw * 0.5,
                "flag": _flag(row.forecast_mw, row.actual_mw),
            }
        )

    energy = daily_energy_mwh(bounded)
    forecast_intervals = int(
        bounded[bounded["forecast_mw"].notna()]["forecast_start_time"].nunique()
    )

    return DecisionResponse(
        delivery_date=day.isoformat(),
        cutoff_local_time=cutoff_time.strftime("%H:%M"),
        cutoff_utc=as_datetime(decision_cutoff_utc(day, cutoff_time)),
        calibration_mode=calibration.mode,
        calibration_n=calibration.n_intervals,
        calibration=calibration_payload(calibration),
        counts=camelize(
            {
                "intervals_expected": int(len(bounded)),
                "intervals_with_forecast": energy["valid_intervals"],
                "intervals_with_actual": int(bounded["actual_mw"].notna().sum()),
                "n_forecast_intervals": forecast_intervals,
            }
        ),
        daily_energy={
            "energy_mwh": energy["energy_mwh"],
            "partial": energy["partial"],
            "unavailable": energy["unavailable"],
            "intervals_with_forecast": energy["valid_intervals"],
            "intervals_expected": energy["expected_intervals"],
            "reason": NO_FORECAST_REASON if energy["unavailable"] else None,
        },
        rows=rows,
    )


@router.get("/forecast/vintages", response_model=VintagesResponse)
def forecast_vintages(
    delivery_date: date = Query(
        default=DELIVERY_MONTH_END, description="delivery day (YYYY-MM-DD), January 2026"
    ),
    cutoff: str = Query(
        default=DEFAULT_CUTOFF_LOCAL_TIME,
        description="assumed cutoff HH:MM Europe/London, on the day before delivery",
    ),
) -> VintagesResponse:
    """Every published version of every hourly interval of one delivery day.

    This is the all-vintages dataset, kept separate from the decision-time
    headline. ``selected`` marks the vintage that was visible at the cutoff;
    versions published *after* the cutoff are included for transparency (a later
    upward revision is a real, documented part of the picture) but were **not**
    visible to the client at decision time.
    """
    day = require_delivery_date(delivery_date)
    cutoff_time = _cutoff(cutoff)
    cutoff_utc = decision_cutoff_utc(day, cutoff_time)

    forecasts, actuals = get_snapshot()
    hours = sorted({forecast_hour_start(slot) for slot in delivery_half_hours(day)})
    hourly_actual = actuals.groupby(actuals["start_time"].dt.floor("h"))["generation_mw"].mean()

    day_forecasts = forecasts[forecasts["start_time"].isin(hours)]

    intervals = []
    n_vintages = n_selected = n_predictive = n_after_cutoff = 0
    for hour in hours:
        vintages = day_forecasts[day_forecasts["start_time"] == hour].sort_values("publish_time")
        eligible = vintages[vintages["publish_time"] <= cutoff_utc]
        selected_publish = eligible["publish_time"].max() if not eligible.empty else None
        actual_mw = number(hourly_actual.get(hour))

        rows = []
        selected_forecast = None
        for record in vintages.itertuples(index=False):
            horizon = float((hour - record.publish_time).total_seconds() / 3600.0)
            age = float((cutoff_utc - record.publish_time).total_seconds() / 3600.0)
            is_selected = selected_publish is not None and record.publish_time == selected_publish
            if is_selected:
                selected_forecast = float(record.generation_mw)
            n_vintages += 1
            n_selected += int(is_selected)
            n_predictive += int(horizon > 0)
            n_after_cutoff += int(record.publish_time > cutoff_utc)
            rows.append(
                {
                    "publish_time": as_datetime(record.publish_time),
                    "forecast_mw": float(record.generation_mw),
                    "horizon_hours": horizon,
                    "forecast_age_hours": age,
                    "selected": is_selected,
                    "predictive": horizon > 0,
                }
            )

        error_mw = (
            selected_forecast - actual_mw
            if selected_forecast is not None and actual_mw is not None
            else None
        )
        intervals.append(
            {
                "forecast_start_time": as_datetime(hour),
                "start_time_local": hour.tz_convert(LONDON_TZ).strftime("%H:%M"),
                "hourly_actual_mw": actual_mw,
                "error_mw": error_mw,
                "vintages": rows,
            }
        )

    return VintagesResponse(
        delivery_date=day.isoformat(),
        cutoff_local_time=cutoff_time.strftime("%H:%M"),
        cutoff_utc=as_datetime(cutoff_utc),
        counts=camelize(
            {
                "intervals": len(intervals),
                "vintages": n_vintages,
                "selected_vintages": n_selected,
                "predictive_vintages": n_predictive,
                "vintages_after_cutoff": n_after_cutoff,
            }
        ),
        intervals=intervals,
    )
