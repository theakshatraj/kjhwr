"""Shared helpers for the API routers.

Validation that is common to every endpoint lives here so the routers stay thin
and the error codes stay consistent: **422** for a request we cannot accept
(malformed cutoff, delivery date outside January 2026, inverted window) and
**404** for a valid request that the snapshot cannot answer.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pandas as pd
from fastapi import HTTPException

from app.config import DELIVERY_MONTH_END, DELIVERY_MONTH_START
from app.schemas import camelize
from app.services.calibration import POOLED_CALIBRATION_NOTE, Calibration


def parse_cutoff(value: str) -> time:
    """Validate an ``HH:MM`` cutoff string and return it as a ``time``."""
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"cutoff must be 'HH:MM', got {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"cutoff out of range: {value!r}")
    return time(hour, minute)


def number(value: Any) -> float | None:
    """NaN/NaT/pd.NA -> None so the JSON stays valid."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return float(value)


def as_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def require_delivery_date(value: date | None, field: str = "deliveryDate") -> date:
    """Delivery days are limited to January 2026; anything else is a 422."""
    if value is None:
        raise HTTPException(status_code=422, detail=f"{field} is required")
    if not (DELIVERY_MONTH_START <= value <= DELIVERY_MONTH_END):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field} must be a delivery day inside the analysed month, "
                f"{DELIVERY_MONTH_START.isoformat()}..{DELIVERY_MONTH_END.isoformat()} "
                f"(January 2026); got {value.isoformat()}"
            ),
        )
    return value


def window_bounds(days_from: date | None, days_to: date | None) -> tuple[date, date]:
    """Resolve and validate an inclusive ``from``/``to`` window (defaults to the month)."""
    start = days_from or DELIVERY_MONTH_START
    end = days_to or DELIVERY_MONTH_END
    require_delivery_date(start, "from")
    require_delivery_date(end, "to")
    if end < start:
        raise HTTPException(status_code=422, detail="'to' must not be earlier than 'from'")
    return start, end


def calibration_payload(calibration: Calibration) -> dict[str, Any]:
    """The calibration block, camelCased (including the nested bounds offsets)."""
    return camelize(
        {
            "mode": calibration.mode,
            "label": calibration.label,
            "strict_no_lookahead": calibration.strict_no_lookahead,
            "available": calibration.available,
            "n_days": calibration.n_days,
            "n_intervals": calibration.n_intervals,
            "warmup_days": calibration.warmup_days,
            "history_from": (
                calibration.history_from.isoformat() if calibration.history_from else None
            ),
            "history_to": (
                calibration.history_to.isoformat() if calibration.history_to else None
            ),
            "percentiles_mw": calibration.percentiles,
            "bounds_mw": calibration.bounds(),
            "pooled": True,
            "pooled_note": POOLED_CALIBRATION_NOTE,
            "reason": calibration.reason,
        }
    )


__all__ = [
    "as_datetime",
    "calibration_payload",
    "number",
    "parse_cutoff",
    "require_delivery_date",
    "window_bounds",
]
