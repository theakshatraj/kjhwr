"""Orientational endpoints: health, metadata, provenance."""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter

from app.config import (
    ACTUALS_SETTLEMENT_FROM,
    ACTUALS_SETTLEMENT_TO,
    DEFAULT_CUTOFF_LOCAL_TIME,
    DELIVERY_MONTH_END,
    DELIVERY_MONTH_START,
    FORECAST_PUBLISH_FROM,
    FORECAST_PUBLISH_TO,
    MIN_CALIBRATION_DAYS,
    MIN_CALIBRATION_INTERVALS,
    PROVENANCE_PATH,
    SNAPSHOT_CAVEAT,
    SOURCE_ATTRIBUTION,
)
from app.routers._helpers import number
from app.schemas import HealthOut, MetaOut, camelize
from app.services.calibration import CALIBRATION_MODES
from app.services.data_store import (
    FORECAST_INTERVAL_MINUTES,
    SETTLEMENT_INTERVAL_MINUTES,
    get_snapshot,
)

router = APIRouter(tags=["meta"])


def _provenance() -> dict | None:
    if not PROVENANCE_PATH.exists():
        return None
    return json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness plus whether the processed snapshot is present."""
    try:
        get_snapshot()
        available = True
    except FileNotFoundError:
        available = False
    return HealthOut(status="ok", data_available=available)


@router.get("/meta", response_model=MetaOut)
def meta() -> MetaOut:
    """Analysis scope, the assumed cutoff, the calibration warm-up and provenance."""
    try:
        forecasts, actuals = get_snapshot()
        available = True
    except FileNotFoundError:
        forecasts, actuals, available = None, None, False

    horizon_range: dict[str, float | None] = {"min": None, "max": None}
    counts: dict[str, int] = {}
    if available and forecasts is not None:
        horizon = forecasts["horizon_hours"]
        horizon_range = {"min": number(horizon.min()), "max": number(horizon.max())}
        counts = {
            "forecast_records": int(len(forecasts)),
            "actual_records": int(len(actuals)),
            "forecast_intervals": int(forecasts["start_time"].nunique()),
            "publish_versions": int(forecasts["publish_time"].nunique()),
        }

    # The December warm-up is the extra history that seeds January calibration.
    warmup = {
        "from": ACTUALS_SETTLEMENT_FROM,
        "to": (DELIVERY_MONTH_START - timedelta(days=1)).isoformat(),
    }

    provenance = _provenance()
    deviations = list(provenance.get("known_deviations", [])) if provenance else []

    return MetaOut(
        delivery_month={
            "start": DELIVERY_MONTH_START.isoformat(),
            "end": DELIVERY_MONTH_END.isoformat(),
        },
        default_cutoff_local_time=DEFAULT_CUTOFF_LOCAL_TIME,
        cutoff_note=(
            "Assumed decision cutoff: the day before delivery at "
            f"{DEFAULT_CUTOFF_LOCAL_TIME} Europe/London. This is an assumption, not an "
            "official gate closure - the real auction deadline differs by exchange."
        ),
        calibration_modes=list(CALIBRATION_MODES),
        min_calibration={
            "days": MIN_CALIBRATION_DAYS,
            "intervals": MIN_CALIBRATION_INTERVALS,
        },
        calibration_warmup=warmup,
        resolution=camelize(
            {
                "forecast_interval_minutes": FORECAST_INTERVAL_MINUTES,
                "settlement_interval_minutes": SETTLEMENT_INTERVAL_MINUTES,
                "settlement_half_hours_per_forecast_value": (
                    FORECAST_INTERVAL_MINUTES // SETTLEMENT_INTERVAL_MINUTES
                ),
                "note": (
                    "WINDFOR is published hourly (24/day); FUELHH is half-hourly (48/day). "
                    "One hourly value covers two settlement half-hours and is never counted "
                    "as two independent observations."
                ),
            }
        ),
        window=camelize(
            {
                "actuals_settlement_from": ACTUALS_SETTLEMENT_FROM,
                "actuals_settlement_to": ACTUALS_SETTLEMENT_TO,
                "forecast_publish_from": FORECAST_PUBLISH_FROM,
                "forecast_publish_to": FORECAST_PUBLISH_TO,
            }
        ),
        counts=camelize(counts),
        horizon_range_hours=horizon_range,
        data_available=available,
        snapshot_notice=SNAPSHOT_CAVEAT,
        attribution=SOURCE_ATTRIBUTION,
        known_deviations=deviations,
        # Verbatim provenance, camelCased like the rest of the surface.
        provenance=camelize(provenance) if provenance else None,
    )
