"""Phase 1 / STEP 3 - validate the processed snapshot.

For every delivery day in scope it reports how many intervals are present
(48 on a normal London day, 46/50 across a DST change), any duplicate
``start_time``, and any gap in the actuals.

Gaps are FLAGGED. They are never filled with zero, and a non-zero exit code is
only returned for structural problems (missing files, duplicates, a day that is
entirely absent) - not for honest gaps.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import (  # noqa: E402
    ACTUALS_SETTLEMENT_FROM,
    ACTUALS_SETTLEMENT_TO,
    FORECAST_PUBLISH_FROM,
    FORECAST_PUBLISH_TO,
    LONDON_TZ,
)
from app.services.data_store import expected_half_hours, load_processed  # noqa: E402


def _day_bounds(day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(day.isoformat(), tz=LONDON_TZ).tz_convert("UTC")
    end = pd.Timestamp((day + timedelta(days=1)).isoformat(), tz=LONDON_TZ).tz_convert("UTC")
    return start, end


def expected_slots_for_day(day: date) -> int:
    """48 normally, 46/50 across a London DST change."""
    start, end = _day_bounds(day)
    return int((end - start) / pd.Timedelta(minutes=30))


def validate(days_from: date, days_to: date) -> int:
    forecasts, actuals = load_processed()
    failures: list[str] = []

    print("=" * 78)
    print("Snapshot validation")
    print("=" * 78)

    # ---- structural checks ------------------------------------------------
    print("\n[structure]")
    for frame, name, keys in (
        (forecasts, "forecasts", ["start_time", "publish_time"]),
        (actuals, "actuals", ["start_time"]),
    ):
        nulls = int(frame[keys].isna().any(axis=1).sum())
        dupes = int(len(frame) - len(frame.drop_duplicates(subset=keys)))
        print(f"  {name:<10} rows={len(frame):<7} null_keys={nulls:<4} duplicate_keys={dupes}")
        if nulls:
            failures.append(f"{name}: {nulls} null key row(s)")
        if dupes:
            failures.append(f"{name}: {dupes} duplicate key row(s)")

    # ---- publish window sanity -------------------------------------------
    pub_min, pub_max = forecasts["publish_time"].min(), forecasts["publish_time"].max()
    print(f"\n[publish window] requested {FORECAST_PUBLISH_FROM} .. {FORECAST_PUBLISH_TO}")
    print(f"                 received  {pub_min.isoformat()} .. {pub_max.isoformat()}")
    if pub_min < pd.Timestamp(FORECAST_PUBLISH_FROM) or pub_max > pd.Timestamp(FORECAST_PUBLISH_TO):
        print("  WARNING: records fall outside the requested publish window - check the")
        print("           publishDateTimeFrom/To parameters are actually being applied.")
        failures.append("forecast publish times outside the requested window")

    # ---- per delivery day -------------------------------------------------
    print(f"\n[per delivery day]  ({days_from.isoformat()} .. {days_to.isoformat()})")
    print(f"  {'day':<12}{'expected':>9}{'actuals':>9}{'dupes':>7}{'gaps':>6}  forecast slots")
    actual_index = set(actuals["start_time"])

    total_gap = 0
    days_with_gaps: list[str] = []
    day = days_from
    while day <= days_to:
        start, end = _day_bounds(day)
        expected = expected_slots_for_day(day)

        in_day = actuals[(actuals["start_time"] >= start) & (actuals["start_time"] < end)]
        present = int(len(in_day))
        dupes = int(len(in_day) - in_day["start_time"].nunique())
        gaps = expected - present
        total_gap += max(gaps, 0)
        if gaps:
            days_with_gaps.append(day.isoformat())

        fc_day = forecasts[(forecasts["start_time"] >= start) & (forecasts["start_time"] < end)]
        slots = int(fc_day["start_time"].nunique())
        flag = "" if gaps == 0 else "  <-- GAP"
        print(f"  {day.isoformat():<12}{expected:>9}{present:>9}{dupes:>7}{max(gaps, 0):>6}  {slots}{flag}")
        if present == 0:
            failures.append(f"{day.isoformat()}: no actuals at all")
        day += timedelta(days=1)

    # ---- gaps, listed -----------------------------------------------------
    print("\n[actuals gaps]")
    expected_index = expected_half_hours(ACTUALS_SETTLEMENT_FROM, ACTUALS_SETTLEMENT_TO)
    missing = [ts for ts in expected_index if ts not in actual_index]
    print(f"  expected half-hours: {len(expected_index)}")
    print(f"  present            : {len(expected_index) - len(missing)}")
    print(f"  missing            : {len(missing)}")
    if missing:
        for ts in missing[:50]:
            print(f"    {ts.tz_convert(LONDON_TZ).strftime('%Y-%m-%d %H:%M %Z')}")
        if len(missing) > 50:
            print(f"    ... and {len(missing) - 50} more")
        print("  NOTE: gaps are reported only. Nothing is filled with zero.")
    else:
        print("  none - actuals coverage is complete.")

    print("\n[forecast coverage for decision-time selection]")
    print("  (detailed per-half-hour coverage is reported by the decision endpoint;")
    print("   this is a coarse sanity check on the raw vintage data)")
    fm = forecasts["start_time"].min()
    fx = forecasts["start_time"].max()
    print(f"  forecast start_time range: {fm.isoformat()} .. {fx.isoformat()}")
    print(f"  distinct start_time values: {forecasts['start_time'].nunique()}")
    print(f"  distinct publish_time values: {forecasts['publish_time'].nunique()}")
    print(f"  vintages per start_time (mean): "
          f"{forecasts.groupby('start_time').size().mean():.1f}")
    negative = int((forecasts["horizon_hours"] < 0).sum())
    print(f"  non-predictive records (horizon < 0): {negative} "
          f"({negative / max(len(forecasts), 1):.1%}) - excluded from horizon analysis")

    print("\n" + "=" * 78)
    if failures:
        print("FAILED structural checks:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("Structural checks passed.")
    if total_gap:
        print(f"{total_gap} actuals interval(s) missing across {len(days_with_gaps)} day(s); "
              "these are flagged, not filled.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the processed snapshot.")
    parser.add_argument("--from", dest="days_from", default=ACTUALS_SETTLEMENT_FROM)
    parser.add_argument("--to", dest="days_to", default=ACTUALS_SETTLEMENT_TO)
    args = parser.parse_args()
    return validate(date.fromisoformat(args.days_from), date.fromisoformat(args.days_to))


if __name__ == "__main__":
    raise SystemExit(main())
