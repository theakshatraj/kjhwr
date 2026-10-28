"""Cleaning, persistence and provenance for the Elexon snapshot.

The pipeline is deliberately boring: fetch raw JSON once, clean it with rules
that are unit-tested, write parquet, and record exactly what happened in
``data/provenance.json``.

Nothing here is allowed to invent data. Missing intervals stay missing; they are
reported by ``scripts/validate_data.py`` and flagged by the API.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from app.config import (
    ACTUALS_SETTLEMENT_FROM,
    ACTUALS_SETTLEMENT_TO,
    FORECAST_PUBLISH_FROM,
    FORECAST_PUBLISH_TO,
    PROCESSED_DIR,
    PROVENANCE_PATH,
    RAW_DIR,
    SOURCE_ATTRIBUTION,
)

logger = logging.getLogger(__name__)

RAW_FORECAST_PATH = RAW_DIR / "windfor_raw.json"
RAW_ACTUALS_PATH = RAW_DIR / "fuelhh_wind_raw.json"
PROCESSED_FORECAST_PATH = PROCESSED_DIR / "forecasts.parquet"
PROCESSED_ACTUALS_PATH = PROCESSED_DIR / "actuals.parquet"

#: CSV mirrors of the same tables. They exist so the serverless function bundle
#: can ship the snapshot without pyarrow (~100 MB installed); pandas reads CSV
#: on its own. Parquet stays the local format because it is smaller and typed.
PROCESSED_FORECAST_CSV = PROCESSED_DIR / "forecasts.csv"
PROCESSED_ACTUALS_CSV = PROCESSED_DIR / "actuals.csv"

FORECAST_KEYS = ["start_time", "publish_time"]
ACTUAL_KEYS = ["start_time"]

#: Elexon returns camelCase field names; everything downstream uses snake_case.
SOURCE_RENAME = {
    "startTime": "start_time",
    "publishTime": "publish_time",
    "generation": "generation_mw",
    "settlementDate": "settlement_date",
    "settlementPeriod": "settlement_period",
    "fuelType": "fuel_type",
}


# ---------------------------------------------------------------------------
# cleaning
# ---------------------------------------------------------------------------
def _to_utc(series: pd.Series) -> pd.Series:
    """Parse ISO timestamps into timezone-aware UTC datetimes."""
    return pd.to_datetime(series, utc=True, format="ISO8601")


def _finish(frame: pd.DataFrame, keys: list[str], sort_by: list[str], label: str) -> pd.DataFrame:
    """Shared tail of the cleaning pipeline: null check, sort, reset index."""
    nulls = frame[keys].isna().any(axis=1).sum()
    if nulls:
        raise ValueError(f"{label}: {nulls} row(s) have a null key column {keys}")
    frame = frame.sort_values(sort_by).reset_index(drop=True)
    return frame


def clean_forecasts(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Raw WINDFOR records -> tidy forecast frame.

    Keeps *every* published version of every ``start_time`` (that is the whole
    point of the project) and adds the derived ``horizon_hours``.
    """
    frame = pd.DataFrame(list(records))
    if frame.empty:
        empty = pd.DataFrame(
            columns=["start_time", "publish_time", "generation_mw", "horizon_hours"]
        )
        empty.attrs["stats"] = {"raw_rows": 0, "dropped_duplicates": 0, "dropped_null_generation": 0}
        return empty

    frame = frame.rename(columns=SOURCE_RENAME)
    frame = frame[["start_time", "publish_time", "generation_mw"]]
    frame["start_time"] = _to_utc(frame["start_time"])
    frame["publish_time"] = _to_utc(frame["publish_time"])
    frame["generation_mw"] = pd.to_numeric(frame["generation_mw"], errors="coerce")

    raw_rows = len(frame)

    # A null generation carries no information and would silently bias every
    # metric, so it is dropped - explicitly counted, never hidden.
    null_generation = int(frame["generation_mw"].isna().sum())
    frame = frame[frame["generation_mw"].notna()]

    # Exact duplicates only. Two different publish times are NOT duplicates here:
    # they are two distinct forecast vintages.
    before = len(frame)
    frame = frame.drop_duplicates(subset=["start_time", "publish_time"], keep="last")
    dropped_duplicates = before - len(frame)

    frame = _finish(frame, FORECAST_KEYS, ["start_time", "publish_time"], "forecasts")
    frame["horizon_hours"] = (
        frame["start_time"] - frame["publish_time"]
    ).dt.total_seconds() / 3600.0

    frame.attrs["stats"] = {
        "raw_rows": raw_rows,
        "dropped_duplicates": dropped_duplicates,
        "dropped_null_generation": null_generation,
    }
    logger.info(
        "forecasts cleaned: %s rows (%s duplicates, %s null generation dropped)",
        len(frame),
        dropped_duplicates,
        null_generation,
    )
    return frame


def clean_actuals(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Raw FUELHH WIND records -> one row per settlement half-hour.

    FUELHH can be re-published, so where several rows share a ``start_time`` the
    row with the latest ``publish_time`` wins. Gaps are left as gaps.
    """
    columns = ["start_time", "generation_mw", "settlement_date", "settlement_period"]
    frame = pd.DataFrame(list(records))
    if frame.empty:
        empty = pd.DataFrame(columns=columns)
        empty.attrs["stats"] = {"raw_rows": 0, "dropped_revisions": 0, "dropped_null_generation": 0}
        return empty

    frame = frame.rename(columns=SOURCE_RENAME)
    keep = ["start_time", "publish_time", "generation_mw", "settlement_date", "settlement_period"]
    frame = frame[[c for c in keep if c in frame.columns]]
    frame["start_time"] = _to_utc(frame["start_time"])
    if "publish_time" in frame.columns:
        frame["publish_time"] = _to_utc(frame["publish_time"])
    frame["generation_mw"] = pd.to_numeric(frame["generation_mw"], errors="coerce")
    if "settlement_period" in frame.columns:
        frame["settlement_period"] = pd.to_numeric(
            frame["settlement_period"], errors="coerce"
        ).astype("Int64")

    raw_rows = len(frame)
    null_generation = int(frame["generation_mw"].isna().sum())
    frame = frame[frame["generation_mw"].notna()]

    # Keep the latest published revision per settlement period.
    if "publish_time" in frame.columns:
        frame = frame.sort_values("publish_time")
    before = len(frame)
    latest = frame.drop_duplicates(subset=["start_time"], keep="last")
    dropped_revisions = before - len(latest)

    latest = latest.drop(columns=[c for c in ["publish_time"] if c in latest.columns])
    latest = _finish(latest, ACTUAL_KEYS, ["start_time"], "actuals")
    latest.attrs["stats"] = {
        "raw_rows": raw_rows,
        "dropped_revisions": dropped_revisions,
        "dropped_null_generation": null_generation,
    }
    logger.info(
        "actuals cleaned: %s rows (%s superseded revision(s), %s null generation dropped)",
        len(latest),
        dropped_revisions,
        null_generation,
    )
    return latest


# ---------------------------------------------------------------------------
# expected interval grids (used by validation and coverage reporting)
# ---------------------------------------------------------------------------
def expected_half_hours(settlement_from: str, settlement_to: str) -> pd.DatetimeIndex:
    """Every half-hour start from ``settlement_from`` 00:00 to ``settlement_to`` 23:30 (UTC).

    Settlement days are London calendar days: 48 half-hours, or 46/50 across a
    DST change. Both boundaries are built as London midnight and converted to
    UTC, so the count comes out right on the clocks-change days too.
    """
    from app.config import LONDON_TZ

    start = pd.Timestamp(settlement_from, tz=LONDON_TZ).tz_convert("UTC")
    end_day = date.fromisoformat(settlement_to) + timedelta(days=1)
    end = pd.Timestamp(end_day.isoformat(), tz=LONDON_TZ).tz_convert("UTC")
    return pd.date_range(start=start, end=end, freq="30min", inclusive="left")


# ---------------------------------------------------------------------------
# resolution mapping (measured, not assumed - see data/feasibility_report.txt)
# ---------------------------------------------------------------------------
#: WINDFOR is published as an hourly series: 24 values per day.
FORECAST_INTERVAL_MINUTES = 60

#: FUELHH settlement periods are 30 minutes: 48 per normal London day.
SETTLEMENT_INTERVAL_MINUTES = 30


def forecast_hour_start(timestamp: pd.Timestamp) -> pd.Timestamp:
    """The hourly forecast interval that a settlement half-hour belongs to.

    WINDFOR carries one MW value per hour, and ``startTime`` is the beginning of
    that hour. So each forecast value covers exactly two settlement half-hours.
    """
    return pd.Timestamp(timestamp).floor("h")


def settlement_slots_for_forecast_hour(
    forecast_hour: pd.Timestamp, steps: int = 2
) -> list[pd.Timestamp]:
    """The settlement half-hours covered by one hourly forecast value."""
    start = pd.Timestamp(forecast_hour)
    return [start + pd.Timedelta(minutes=SETTLEMENT_INTERVAL_MINUTES * i) for i in range(steps)]


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def _read_raw(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"missing raw file {path}; run scripts/fetch_data.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def write_processed(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    forecasts.to_parquet(PROCESSED_FORECAST_PATH, index=False)
    actuals.to_parquet(PROCESSED_ACTUALS_PATH, index=False)
    # Mirror both tables as CSV for the Vercel function bundle.
    forecasts.to_csv(PROCESSED_FORECAST_CSV, index=False)
    actuals.to_csv(PROCESSED_ACTUALS_CSV, index=False)


def _read_snapshot(parquet: Path, csv: Path, time_columns: list[str]) -> pd.DataFrame:
    """Read one snapshot table, preferring parquet and falling back to CSV.

    Both formats resolve through the same ``pathlib`` paths, so a local run and a
    Vercel function read the snapshot in exactly the same way; only the shipped
    format differs.
    """
    if parquet.exists():
        return pd.read_parquet(parquet)
    if csv.exists():
        frame = pd.read_csv(csv)
        for column in time_columns:
            frame[column] = pd.to_datetime(frame[column], utc=True, format="ISO8601")
        return frame
    raise FileNotFoundError(
        f"processed snapshot not found ({parquet} or {csv}); "
        "run scripts/fetch_data.py to build it"
    )


def load_processed() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the cleaned snapshot. Raises if the pipeline has not been run."""
    forecasts = _read_snapshot(PROCESSED_FORECAST_PATH, PROCESSED_FORECAST_CSV, FORECAST_KEYS)
    actuals = _read_snapshot(PROCESSED_ACTUALS_PATH, PROCESSED_ACTUALS_CSV, ACTUAL_KEYS)
    return forecasts, actuals


@lru_cache(maxsize=1)
def get_snapshot() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Processed snapshot, read once per process. Treat the frames as read-only."""
    return load_processed()


def summarise(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    if frame.empty or column not in frame.columns:
        return {"count": 0}
    series = frame[column]
    return {
        "count": int(series.notna().sum()),
        "min": series.min().isoformat(),
        "max": series.max().isoformat(),
    }


def write_provenance(
    raw_forecast_count: int,
    raw_actual_count: int,
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    api_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Record everything needed to reproduce and audit the snapshot."""
    actual_start = set(actuals["start_time"]) if not actuals.empty else set()
    expected = expected_half_hours(ACTUALS_SETTLEMENT_FROM, ACTUALS_SETTLEMENT_TO)
    missing_actuals = [ts for ts in expected if ts not in actual_start]

    provenance = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_notice": (
            "Fixed historical analysis snapshot built from Elexon BMRS. "
            "Not a live trading system."
        ),
        "source": {
            "provider": "Elexon Insights Solution (BMRS)",
            "base_url": "https://data.elexon.co.uk/bmrs/api/v1",
            "datasets": {
                "forecasts": {
                    "dataset": "WINDFOR",
                    "path": "/datasets/WINDFOR/stream",
                    "parameters": {
                        "publishDateTimeFrom": FORECAST_PUBLISH_FROM,
                        "publishDateTimeTo": FORECAST_PUBLISH_TO,
                    },
                    "note": (
                        "Filtered on PUBLISH time. Passing from/to instead is silently "
                        "ignored and returns only the latest forecast."
                    ),
                },
                "actuals": {
                    "dataset": "FUELHH",
                    "path": "/datasets/FUELHH/stream",
                    "parameters": {
                        "settlementDateFrom": ACTUALS_SETTLEMENT_FROM,
                        "settlementDateTo": ACTUALS_SETTLEMENT_TO,
                        "fuelType": "WIND",
                    },
                },
            },
            "attribution": SOURCE_ATTRIBUTION,
            "licence": (
                "Elexon Open Data Licence - reuse permitted with attribution to "
                "Elexon. Redistribution must keep this attribution and licence note."
            ),
        },
        "request_log": api_calls,
        "row_counts": {
            "raw_forecast_records": raw_forecast_count,
            "raw_actual_records": raw_actual_count,
            "processed_forecast_records": int(len(forecasts)),
            "processed_actual_records": int(len(actuals)),
        },
        "cleaning_counts": {
            "forecasts": forecasts.attrs.get("stats", {}),
            "actuals": actuals.attrs.get("stats", {}),
        },
        "coverage": {
            "actuals_expected_intervals": int(len(expected)),
            "actuals_present_intervals": int(len(actual_start)),
            "actuals_missing_intervals": len(missing_actuals),
            "actuals_missing_sample": [ts.isoformat() for ts in missing_actuals[:24]],
        },
        "ranges": {
            "forecast_start_time": summarise(forecasts, "start_time"),
            "forecast_publish_time": summarise(forecasts, "publish_time"),
            "actual_start_time": summarise(actuals, "start_time"),
        },
        "resolution": {
            "forecast_interval_minutes": FORECAST_INTERVAL_MINUTES,
            "settlement_interval_minutes": SETTLEMENT_INTERVAL_MINUTES,
            "settlement_half_hours_per_forecast_value": (
                FORECAST_INTERVAL_MINUTES // SETTLEMENT_INTERVAL_MINUTES
            ),
            "measured_note": (
                "Measured from the raw snapshot (see data/feasibility_report.txt): WINDFOR "
                "publishes one MW value per hour (24 per day) with startTime at the top of "
                "the hour, while FUELHH publishes one MW value per settlement half-hour "
                "(48 per normal day). Each hourly forecast value therefore maps onto exactly "
                "two settlement half-hours. Accuracy metrics must align at native resolution: "
                "report both unique forecast intervals and display half-hours, and never count "
                "the same hourly value as two independent observations."
            ),
        },
        "cleaning_steps": [
            "parse startTime/publishTime as timezone-aware UTC datetimes",
            "coerce generation to numeric MW",
            "drop rows whose generation is null (counted in cleaning_counts)",
            "drop exact duplicate (start_time, publish_time) forecast rows",
            "for actuals keep one row per start_time, preferring the latest revision",
            "sort by start_time then publish_time",
            "assert start_time and publish_time are non-null",
            "derive horizon_hours = (start_time - publish_time) / 1h",
            "NO gap filling: missing intervals are reported, never zero-filled",
        ],
        "known_deviations": [
            "WINDFOR is natively hourly (24 slots/day), not half-hourly as the brief "
            "assumes; delivery intervals remain half-hourly and the hourly value is "
            "applied to both constituent half-hours without interpolation.",
            "The decision cutoff time is an ASSUMPTION (default 09:00 Europe/London on "
            "D-1), not an official gate closure.",
        ],
    }

    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE_PATH.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return provenance
