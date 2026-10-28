"""Decision-time forecast selection (the headline dataset).

For every settlement half-hour of a delivery day D we pick the *latest* WINDFOR
value that a client could actually have seen at the assumed decision cutoff on
D-1:

    eligible  := publish_time <= cutoff(D)
    selected  := the eligible record with the greatest publish_time

Resolution (measured, see ``data/feasibility_report.txt``): WINDFOR is published
hourly, FUELHH half-hourly. One hourly forecast value therefore covers two
settlement half-hours, and both rows carry the *same* forecast value, publish
time and horizon. That is the mapping; we never interpolate and we never treat
the two rows as two independent forecast observations.

Missing forecasts are preserved: the delivery grid is always complete, slots
without an eligible forecast carry ``forecast_mw = NaN`` and are flagged
``missing_forecast = True``. Slots are never dropped and never filled.

Delivery days are London calendar days (the portal's scope), so DST-transition
days have 46 or 50 half-hours rather than 48. ``tz`` parameterises the *cutoff*
instant; the delivery grid stays London-local.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from functools import lru_cache

import pandas as pd

from app.config import (
    ACTUALS_SETTLEMENT_FROM,
    ACTUALS_SETTLEMENT_TO,
    DEFAULT_CUTOFF_TIME,
    DELIVERY_MONTH_END,
    DELIVERY_MONTH_START,
    TIMEZONE_NAME,
    decision_cutoff_utc,
)
from app.services.data_store import (
    expected_half_hours,
    forecast_hour_start,
    get_snapshot,
)
from app.services.metrics import horizon_bucket

#: Columns of the decision-time dataset, in presentation order.
DECISION_COLUMNS = [
    "delivery_date",
    "start_time",           # delivery settlement half-hour (UTC)
    "forecast_start_time",  # hourly WINDFOR interval used (UTC)
    "forecast_mw",
    "publish_time",
    "horizon_hours",
    "forecast_age_hours",
    "actual_mw",
    "error_mw",
    "missing_forecast",
]


def delivery_half_hours(delivery_date: date) -> pd.DatetimeIndex:
    """The settlement half-hour slots of a London delivery day (48, or 46/50 on DST days)."""
    iso = delivery_date.isoformat()
    return expected_half_hours(iso, iso)


def select_decision_forecasts(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    delivery_date: date,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    tz: str = TIMEZONE_NAME,
) -> pd.DataFrame:
    """One row per delivery half-hour, carrying the forecast visible at the cutoff.

    ``cutoff`` is the local time (in ``tz``) on the day *before* delivery. A
    forecast published exactly at the cutoff is included; one second later is not.
    """
    cutoff_utc = decision_cutoff_utc(delivery_date, cutoff, tz)
    slots = delivery_half_hours(delivery_date)
    slot_hour = {ts: forecast_hour_start(ts) for ts in slots}
    needed_hours = set(slot_hour.values())

    eligible = forecasts[
        (forecasts["publish_time"] <= cutoff_utc)
        & (forecasts["start_time"].isin(needed_hours))
    ]
    # Latest published version per hourly interval == what the client saw.
    selected = eligible.sort_values("publish_time").drop_duplicates(
        subset=["start_time"], keep="last"
    )
    by_hour = {
        row.start_time: row
        for row in selected[["start_time", "publish_time", "generation_mw"]].itertuples(
            index=False
        )
    }
    actual_by_slot = actuals.set_index("start_time")["generation_mw"].to_dict()

    rows: list[dict] = []
    for ts in slots:
        hour = slot_hour[ts]
        record = by_hour.get(hour)
        forecast_mw = float(record.generation_mw) if record is not None else float("nan")
        publish_time = record.publish_time if record is not None else pd.NaT
        horizon = (
            float((hour - publish_time).total_seconds() / 3600.0)
            if record is not None
            else float("nan")
        )
        age = (
            float((cutoff_utc - publish_time).total_seconds() / 3600.0)
            if record is not None
            else float("nan")
        )
        actual_mw = actual_by_slot.get(ts, float("nan"))
        error_mw = (
            forecast_mw - actual_mw
            if pd.notna(forecast_mw) and pd.notna(actual_mw)
            else float("nan")
        )
        rows.append(
            {
                "delivery_date": delivery_date,
                "start_time": ts,
                "forecast_start_time": hour,
                "forecast_mw": forecast_mw,
                "publish_time": publish_time,
                "horizon_hours": horizon,
                "forecast_age_hours": age,
                "actual_mw": actual_mw,
                "error_mw": error_mw,
                "missing_forecast": record is None,
            }
        )

    frame = pd.DataFrame(rows, columns=DECISION_COLUMNS)
    return frame


def get_decision_forecast(
    delivery_date: date,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    tz: str = TIMEZONE_NAME,
) -> pd.DataFrame:
    """Decision-time rows for one delivery day, straight from the snapshot."""
    forecasts, actuals = get_snapshot()
    return select_decision_forecasts(forecasts, actuals, delivery_date, cutoff, tz)


def build_decision_dataset(
    from_date: date,
    to_date: date,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    tz: str = TIMEZONE_NAME,
    *,
    forecasts: pd.DataFrame | None = None,
    actuals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Stack the per-day decision selection over an inclusive date range.

    ``from_date`` should reach back into the December warm-up so that January
    decisions have a seeded calibration history. ``forecasts``/``actuals`` are
    injectable for tests; by default they come from the processed snapshot.
    """
    if forecasts is None or actuals is None:
        forecasts, actuals = get_snapshot()
    days = [
        from_date + timedelta(days=i) for i in range((to_date - from_date).days + 1)
    ]
    frames = [
        select_decision_forecasts(forecasts, actuals, day, cutoff, tz) for day in days
    ]
    if not frames:
        return pd.DataFrame(columns=DECISION_COLUMNS)
    dataset = pd.concat(frames, ignore_index=True)
    return dataset.sort_values("start_time").reset_index(drop=True)


def dataset_counts(dataset: pd.DataFrame) -> dict[str, int]:
    """Sample sizes that must accompany every headline metric.

    ``n_half_hours`` is the display grid; ``n_forecast_intervals`` is the number
    of *distinct* hourly forecast values behind those rows (the effective
    independent sample). Reporting both stops the hourly value being counted
    twice as two independent observations.
    """
    if dataset.empty:
        return {"n_half_hours": 0, "n_forecast_intervals": 0, "n_days": 0}
    scored = dataset[dataset["forecast_mw"].notna() & dataset["actual_mw"].notna()]
    return {
        "n_half_hours": int(len(scored)),
        "n_forecast_intervals": int(scored["forecast_start_time"].nunique()),
        "n_days": int(scored["delivery_date"].nunique()),
    }


def build_all_vintages_dataset(
    forecasts: pd.DataFrame, actuals: pd.DataFrame
) -> pd.DataFrame:
    """Every forecast version vs the actual, at native (hourly) resolution.

    Used only for the *lead-time* comparison. Because WINDFOR is hourly it is
    compared against the hourly mean of the two constituent settlement
    half-hours, so one row == one forecast record == one honest error.

    Records with ``horizon_hours <= 0`` (published at or after their target time)
    are not valid advance predictions. They are kept here with
    ``predictive = False`` so that ``metrics.by_horizon`` can exclude them
    explicitly and report how many, rather than the exclusion happening silently
    in this loader.
    """
    acts = actuals.copy()
    acts["hour"] = acts["start_time"].dt.floor("h")
    hourly_actual = acts.groupby("hour")["generation_mw"].mean()

    frame = forecasts.copy()
    frame["hourly_actual_mw"] = frame["start_time"].map(hourly_actual)
    frame = frame[frame["hourly_actual_mw"].notna()].copy()
    frame["predictive"] = frame["horizon_hours"] > 0
    frame["error_mw"] = frame["generation_mw"] - frame["hourly_actual_mw"]
    frame["horizon_bucket"] = frame["horizon_hours"].map(horizon_bucket)
    return frame


# ---------------------------------------------------------------------------
# cached accessors (read-only: callers must not mutate the returned frames)
# ---------------------------------------------------------------------------
def analysis_days() -> list[date]:
    """Every delivery day spanned by the actuals window (December warm-up + January)."""
    start = date.fromisoformat(ACTUALS_SETTLEMENT_FROM)
    end = date.fromisoformat(ACTUALS_SETTLEMENT_TO)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


@lru_cache(maxsize=4)
def get_decision_dataset(
    cutoff: time = DEFAULT_CUTOFF_TIME, tz: str = TIMEZONE_NAME
) -> pd.DataFrame:
    """Decision-time dataset across the whole snapshot (December + January)."""
    start = date.fromisoformat(ACTUALS_SETTLEMENT_FROM)
    end = date.fromisoformat(ACTUALS_SETTLEMENT_TO)
    return build_decision_dataset(start, end, cutoff, tz)


def delivery_month_dataset(
    cutoff: time = DEFAULT_CUTOFF_TIME, tz: str = TIMEZONE_NAME
) -> pd.DataFrame:
    """The January part of the decision-time dataset - the headline scope."""
    dataset = get_decision_dataset(cutoff, tz)
    mask = (dataset["delivery_date"] >= DELIVERY_MONTH_START) & (
        dataset["delivery_date"] <= DELIVERY_MONTH_END
    )
    return dataset[mask]


@lru_cache(maxsize=1)
def get_all_vintages_dataset() -> pd.DataFrame:
    forecasts, actuals = get_snapshot()
    return build_all_vintages_dataset(forecasts, actuals)
