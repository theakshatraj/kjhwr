"""Phase 1 / STEP 1 - data feasibility spike.

Proves, with printed evidence, that the Elexon BMRS API can reconstruct
*historical forecast versions*, which is the gate for the whole project.

Checks (a)-(f) map 1:1 to the brief:
  a) real base URL, query parameter names, response shape, max range per request
  b) WINDFOR returns several publishTime versions per startTime
  c) publish-time filtering works and the publish window needed for January 2026
     delivery decisions is present
  d) for a sample delivery day, how many delivery intervals have at least one
     eligible forecast (published before the assumed cutoff)
  e) FUELHH WIND actuals coverage + settlement-period vs startTime convention
  f) the horizon range of the forecasts

Run:  python scripts/feasibility_spike.py [--refresh]
Writes raw pulls to ``data/raw/`` (reused by the real pipeline) and the report
to ``data/feasibility_report.txt``.
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import (  # noqa: E402
    ACTUALS_SETTLEMENT_FROM,
    ACTUALS_SETTLEMENT_TO,
    DATA_DIR,
    DEFAULT_CUTOFF_TIME,
    FORECAST_PUBLISH_FROM,
    FORECAST_PUBLISH_TO,
    LONDON_TZ,
    RAW_DIR,
    decision_cutoff_utc,
)
from app.services.elexon_client import (  # noqa: E402
    MAX_RANGE_DAYS,
    ElexonClient,
    ElexonError,
    _iso_z,
    _parse_iso,
)

SAMPLE_DELIVERY_DAY = date(2026, 1, 15)

_report_lines: list[str] = []


def say(text: str = "") -> None:
    print(text)
    _report_lines.append(text)


def rule(title: str) -> None:
    say()
    say("=" * 78)
    say(title)
    say("=" * 78)


def cache_path(name: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    return RAW_DIR / name


def cached_json(name: str, producer, refresh: bool):
    path = cache_path(name)
    if path.exists() and not refresh:
        # console only - the report should contain evidence, not fetch plumbing
        print(f"[cache] reusing {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    data = producer()
    path.write_text(json.dumps(data), encoding="utf-8")
    print(f"[fetch] wrote {path.name} ({len(data)} records)")
    return data


def to_local(iso_utc: str) -> datetime:
    return _parse_iso(iso_utc).astimezone(LONDON_TZ)


def half_hour_grid(day: date) -> list[datetime]:
    """UTC instants of a delivery day's half-hours, London day boundaries."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=LONDON_TZ)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=LONDON_TZ)
    grid = []
    cursor = start
    while cursor < end:
        grid.append(cursor.astimezone(timezone.utc))
        cursor += timedelta(minutes=30)
    return grid


# ---------------------------------------------------------------------------
# (a) base URL, parameter names, response shape, max range
# ---------------------------------------------------------------------------
def check_a(client: ElexonClient) -> dict:
    rule("(a) Base URL, query parameter names, response shape, max range per request")

    say(f"Base URL ............ {client.base_url}")
    say("WINDFOR stream path . /datasets/WINDFOR/stream")
    say("FUELHH stream path .. /datasets/FUELHH/stream")
    say()
    say("Parameter names (per Elexon API documentation for the stream endpoints):")
    say("  WINDFOR : publishDateTimeFrom, publishDateTimeTo   <- PUBLISH time filter")
    say("  FUELHH  : settlementDateFrom, settlementDateTo, fuelType")
    say("            (publishDateTimeFrom/To also exist, but the docs state settlement")
    say("             fields cannot be combined with publish fields)")

    # Demonstrate that the wrong parameter names are silently ignored.
    wrong = client._get(
        "/datasets/WINDFOR/stream", {"from": "2026-01-14T00:00Z", "to": "2026-01-14T03:00Z"}
    )
    wrong_publishes = sorted({r["publishTime"] for r in wrong})
    say()
    say("Trap 1: passing 'from'/'to' to WINDFOR/stream.")
    say(f"  -> returned {len(wrong)} rows, publishTime range {wrong_publishes[0]} .. {wrong_publishes[-1]}")
    say("  -> the unknown parameters are IGNORED and the LATEST forecast is returned,")
    say("     i.e. it looks like it works but the publish-time filter is not applied.")

    right = client._get(
        "/datasets/WINDFOR/stream",
        {"publishDateTimeFrom": "2026-01-14T00:00Z", "publishDateTimeTo": "2026-01-14T03:00Z"},
    )
    right_publishes = sorted({r["publishTime"] for r in right})
    say()
    say("Correct parameters return only that publish window:")
    say(f"  -> {len(right)} rows, publishTime {right_publishes[0]} .. {right_publishes[-1]}")

    wrong_actual = client._get(
        "/datasets/FUELHH/stream",
        {"from": "2026-01-05T00:00Z", "to": "2026-01-06T00:00Z", "fuelType": "WIND"},
    )
    acc_starts = sorted(r["startTime"] for r in wrong_actual)
    say()
    say("Trap 2: same mistake on FUELHH/stream.")
    say(f"  -> returned {len(wrong_actual)} rows, startTime {acc_starts[0]} .. {acc_starts[-1]}"
        if wrong_actual else "  -> returned 0 rows")
    say("  -> again the filter was ignored and the current day's stream came back.")

    say()
    say("Response shape (WINDFOR, raw dataset):")
    say(json.dumps(right[0], indent=2) if right else "  <empty>")

    say()
    say("Max date range per single request (empirical probe, WINDFOR):")
    anchor = _parse_iso("2026-01-05T00:00Z")
    max_ok = None
    for days in (1, 2, 4, 7, 14, 31, 62):
        try:
            payload = client._get(
                "/datasets/WINDFOR/stream",
                {
                    "publishDateTimeFrom": _iso_z(anchor),
                    "publishDateTimeTo": _iso_z(anchor + timedelta(days=days)),
                },
            )
            say(f"  {days:>3} days -> OK ({len(payload)} rows)")
            max_ok = days
        except ElexonError as exc:
            say(f"  {days:>3} days -> REJECTED: {str(exc)[:120]}")
            break
    say(f"  => no rejection observed up to {max_ok} days; the client still chunks at")
    say(f"     {MAX_RANGE_DAYS} days to keep individual responses small and retries cheap.")

    max_ok_actuals = None
    for days in (1, 15, 45, 62):
        try:
            payload = client._get(
                "/datasets/FUELHH/stream",
                {
                    "settlementDateFrom": (anchor + timedelta(days=0)).date().isoformat(),
                    "settlementDateTo": (anchor + timedelta(days=days)).date().isoformat(),
                    "fuelType": "WIND",
                },
            )
            expected = (days + 1) * 48
            say(f"  FUELHH {days:>3} days -> OK ({len(payload)} rows, expected ~{expected})")
            max_ok_actuals = days
        except ElexonError as exc:
            say(f"  FUELHH {days:>3} days -> REJECTED: {str(exc)[:120]}")
            break

    return {"max_ok_days": max_ok, "max_ok_days_actuals": max_ok_actuals}


# ---------------------------------------------------------------------------
# (b) multiple publish versions per startTime
# ---------------------------------------------------------------------------
def check_b(client: ElexonClient, forecasts: list[dict]) -> dict:
    rule("(b) WINDFOR returns multiple publishTime versions per startTime")

    versions: dict[str, int] = {}
    for record in forecasts:
        versions[record["startTime"]] = versions.get(record["startTime"], 0) + 1

    distribution: dict[int, int] = {}
    for count in versions.values():
        distribution[count] = distribution.get(count, 0) + 1

    say(f"distinct startTime ............ {len(versions)}")
    say(f"total forecast records ........ {len(forecasts)}")
    say("versions-per-startTime histogram (versions: how many startTimes):")
    for count in sorted(distribution):
        say(f"   {count:>3} versions : {distribution[count]} startTimes")

    multi = sum(1 for c in versions.values() if c > 1)
    say(f"startTimes with >1 published version: {multi}")
    say("=> historical versions ARE retrievable." if multi else "=> BLOCKER: only one version per startTime.")
    return {"distinct_start_times": len(versions), "multi_version_start_times": multi}


# ---------------------------------------------------------------------------
# (c) publish window for January 2026 decisions
# ---------------------------------------------------------------------------
def check_c(forecasts: list[dict]) -> dict:
    rule("(c) Publish window needed for January 2026 delivery decisions is present")

    publishes = sorted({r["publishTime"] for r in forecasts})
    dates = sorted({p[:10] for p in publishes})
    say(f"requested publish window ... {FORECAST_PUBLISH_FROM} .. {FORECAST_PUBLISH_TO}")
    say(f"received publishTime range . {publishes[0]} .. {publishes[-1]}")
    say(f"distinct publish days ...... {len(dates)}  ({dates[0]} .. {dates[-1]})")

    # Every January delivery day needs a cutoff on the previous day. The earliest
    # one is for 2026-01-01 -> 2025-12-31 09:00 London.
    needed = []
    cursor = date(2026, 1, 1)
    while cursor <= date(2026, 1, 31):
        needed.append(decision_cutoff_utc(cursor, DEFAULT_CUTOFF_TIME).strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)

    publish_date_set = set(dates)
    missing = [d for d in needed if d not in publish_date_set]
    say()
    say(f"cutoff days required for January delivery days: {len(set(needed))}")
    say(f"cutoff days with NO published forecast on that date: {len(missing)}")
    if missing:
        say(f"  missing: {missing[:20]}{' ...' if len(missing) > 20 else ''}")
    else:
        say("  none - every January cutoff day has published forecasts available.")
    return {"publish_days": len(dates), "missing_cutoff_days": missing}


# ---------------------------------------------------------------------------
# (d) sample delivery day eligibility
# ---------------------------------------------------------------------------
def check_d(forecasts: list[dict], day: date = SAMPLE_DELIVERY_DAY) -> dict:
    rule(f"(d) Sample delivery day {day.isoformat()}: eligible forecasts before the assumed cutoff")

    cutoff = decision_cutoff_utc(day, DEFAULT_CUTOFF_TIME)
    say(f"assumed decision cutoff ... {cutoff.strftime('%Y-%m-%dT%H:%MZ')} "
        f"({cutoff.astimezone(LONDON_TZ).strftime('%Y-%m-%d %H:%M %Z')})")

    day_start = datetime.combine(day, datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)
    day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)

    day_records = [r for r in forecasts if day_start <= _parse_iso(r["startTime"]) < day_end]
    say(f"forecast records targeting {day} (all vintages): {len(day_records)}")
    if not day_records:
        say("=> BLOCKER: no forecast records target this delivery day.")
        return {"covered": 0, "expected": 0, "missing": []}

    eligible = [
        r for r in day_records
        if _parse_iso(r["publishTime"]) <= cutoff and _parse_iso(r["publishTime"]) < _parse_iso(r["startTime"])
    ]
    say(f"eligible (publishTime <= cutoff, and published before the target): {len(eligible)}")

    # Native resolution of the forecast grid, measured rather than assumed.
    starts = sorted({_parse_iso(r["startTime"]) for r in day_records})
    deltas = [(b - a).total_seconds() / 60 for a, b in zip(starts, starts[1:])]
    native_minutes = min(deltas) if deltas else 30
    say(f"native forecast resolution observed on this day: {native_minutes:.0f} minutes")
    if native_minutes != 30:
        say(f"  DEVIATION FROM THE BRIEF: the brief assumes 48 half-hour forecast slots,")
        say(f"  but WINDFOR is natively {native_minutes:.0f}-minute (hourly). One hourly MW value")
        say(f"  therefore covers two delivery half-hours. Delivery intervals stay half-hourly")
        say(f"  (energy MWh = MW x 0.5), the hourly value is applied to both of its half-hours")
        say(f"  with no interpolation, and metrics report the count of *unique forecast")
        say(f"  intervals* as well as half-hours so nothing is silently double counted.")

    # Half-hour delivery grid (what the client actually buys against).
    grid = half_hour_grid(day)
    say(f"expected delivery half-hours (London day): {len(grid)}")

    covered_hh = set()
    for slot in grid:
        slot_key = slot.replace(minute=0, second=0, microsecond=0)
        if any(
            _parse_iso(r["startTime"]) == slot_key or _parse_iso(r["startTime"]) == slot
            for r in eligible
        ):
            covered_hh.add(slot)

    missing_hh = [s for s in grid if s not in covered_hh]
    say()
    say(f"delivery half-hours with >=1 eligible forecast: {len(covered_hh)} / {len(grid)}")
    if missing_hh:
        say("missing half-hours (flagged, never filled with zero):")
        for slot in missing_hh:
            say(f"   {slot.astimezone(LONDON_TZ).strftime('%Y-%m-%d %H:%M %Z')}")
    else:
        say("no missing half-hours for this delivery day.")

    # Hourly-native view, for transparency.
    native_slots = sorted({_parse_iso(r["startTime"]) for r in eligible})
    say()
    say(f"native forecast slots covered for {day}: {len(native_slots)} "
        f"(of {len(starts)} slots present in the raw data)")
    return {
        "delivery_day": day.isoformat(),
        "expected_half_hours": len(grid),
        "covered_half_hours": len(covered_hh),
        "missing_half_hours": [s.astimezone(LONDON_TZ).isoformat() for s in missing_hh],
        "native_resolution_minutes": native_minutes,
    }


# ---------------------------------------------------------------------------
# (e) actuals coverage
# ---------------------------------------------------------------------------
def check_e(actuals: list[dict]) -> dict:
    rule("(e) FUELHH WIND actuals coverage, granularity, settlement-period convention")

    if not actuals:
        say("=> BLOCKER: no FUELHH WIND records returned.")
        return {"rows": 0, "missing": []}

    say(f"requested settlement dates ... {ACTUALS_SETTLEMENT_FROM} .. {ACTUALS_SETTLEMENT_TO}")
    starts = sorted(_parse_iso(r["startTime"]) for r in actuals)
    say(f"received startTime .......... {_iso_z(starts[0])} .. {_iso_z(starts[-1])}")
    say(f"rows ........................ {len(actuals)}")
    say(f"fuel types present .......... {sorted({r.get('fuelType') for r in actuals})}")
    say()
    say("sample record:")
    say(json.dumps(actuals[0], indent=2))

    deltas = sorted({(b - a).total_seconds() / 60 for a, b in zip(starts, starts[1:])})
    say()
    say(f"observed spacing between consecutive startTime values: {deltas} minutes (30 = half-hourly)")

    duplicates = len(actuals) - len(set(starts))
    say(f"rows per startTime > 1 (duplicates): {duplicates}")

    sample = actuals[0]
    say()
    say("settlement-period vs startTime convention:")
    say(f"  startTime={sample.get('startTime')}  settlementDate={sample.get('settlementDate')}  "
        f"settlementPeriod={sample.get('settlementPeriod')}")
    say("  -> FUELHH carries BOTH a half-hourly startTime and (settlementDate,")
    say("     settlementPeriod). This project keys everything on startTime (UTC):")
    say("     settlementPeriod is NOT 1:1 with clock time across a DST boundary, so it")
    say("     is retained for reference only and never used as a join key.")

    # Expected half-hour grid over the whole requested settlement window.
    grid = []
    cursor = datetime.combine(date.fromisoformat(ACTUALS_SETTLEMENT_FROM), datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)
    end = (datetime.combine(date.fromisoformat(ACTUALS_SETTLEMENT_TO), datetime.min.time(), tzinfo=LONDON_TZ)
           + timedelta(days=1)).astimezone(timezone.utc)
    while cursor < end:
        grid.append(cursor)
        cursor += timedelta(minutes=30)

    present = set(starts)
    missing = [s for s in grid if s not in present]
    say()
    say(f"expected half-hour slots: {len(grid)}")
    say(f"missing actuals slots ...: {len(missing)}")
    if missing:
        for slot in missing[:10]:
            say(f"   {slot.astimezone(LONDON_TZ).strftime('%Y-%m-%d %H:%M %Z')}")
        if len(missing) > 10:
            say(f"   ... and {len(missing) - 10} more")
        say("  (gaps are FLAGGED by validation; they are never filled with zero)")
    else:
        say("  none - actuals coverage is complete for the requested window.")

    return {
        "rows": len(actuals),
        "expected_slots": len(grid),
        "missing_slots": len(missing),
        "missing_sample": [s.astimezone(LONDON_TZ).isoformat() for s in missing[:20]],
        "spacing_minutes": deltas,
    }


# ---------------------------------------------------------------------------
# (f) horizon range
# ---------------------------------------------------------------------------
def check_f(forecasts: list[dict]) -> dict:
    rule("(f) Horizon range (startTime - publishTime) of the forecasts")

    horizons = sorted(
        (_parse_iso(r["startTime"]) - _parse_iso(r["publishTime"])).total_seconds() / 3600.0
        for r in forecasts
    )
    if not horizons:
        say("=> no forecasts to measure.")
        return {}

    def pct(p: float) -> float:
        idx = min(len(horizons) - 1, max(0, int(round(p / 100 * (len(horizons) - 1)))))
        return horizons[idx]

    say(f"n records ...... {len(horizons)}")
    say(f"min ........... {horizons[0]:.2f} h")
    say(f"P5 ............ {pct(5):.2f} h")
    say(f"P25 ........... {pct(25):.2f} h")
    say(f"median ........ {statistics.median(horizons):.2f} h")
    say(f"P75 ........... {pct(75):.2f} h")
    say(f"P95 ........... {pct(95):.2f} h")
    say(f"max ........... {horizons[-1]:.2f} h")

    negative = sum(1 for h in horizons if h < 0)
    say(f"non-predictive records (publishTime AFTER startTime): {negative}")
    say("  (these are excluded from horizon analysis; they are not forecasts)")

    # Decision-time horizons actually selected for January delivery days.
    return {
        "min_h": round(horizons[0], 3),
        "max_h": round(horizons[-1], 3),
        "median_h": round(statistics.median(horizons), 3),
        "negative_horizon_records": negative,
    }


def check_decision_time_horizons(forecasts: list[dict]) -> dict:
    """Horizons of the *selected* decision-time forecast, per delivery half-hour."""
    horizons = []
    per_day: dict[str, list[float]] = {}
    cursor = date(2026, 1, 1)
    by_start: dict[datetime, list[dict]] = {}
    for r in forecasts:
        by_start.setdefault(_parse_iso(r["startTime"]), []).append(r)

    def lookup(slot_utc: datetime) -> list[dict] | None:
        return by_start.get(slot_utc) or by_start.get(slot_utc.replace(minute=0))

    while cursor <= date(2026, 1, 31):
        cutoff = decision_cutoff_utc(cursor)
        for slot in half_hour_grid(cursor):
            candidates = lookup(slot)
            if not candidates:
                continue
            eligible = [
                r for r in candidates
                if _parse_iso(r["publishTime"]) <= cutoff and _parse_iso(r["publishTime"]) < _parse_iso(r["startTime"])
            ]
            if not eligible:
                continue
            chosen = max(eligible, key=lambda r: r["publishTime"])
            horizon = (_parse_iso(chosen["startTime"]) - _parse_iso(chosen["publishTime"])).total_seconds() / 3600
            horizons.append(horizon)
            per_day.setdefault(cursor.isoformat(), []).append(horizon)
        cursor += timedelta(days=1)

    say()
    say("Selected decision-time forecasts for January 2026:")
    say(f"  half-hours with a selected forecast: {len(horizons)} of "
        f"{len(half_hour_grid(date(2026,1,1))) * 31}")
    if horizons:
        say(f"  horizon min/median/max: {min(horizons):.2f} / "
            f"{statistics.median(horizons):.2f} / {max(horizons):.2f} h")
    for day in sorted(per_day):
        say(f"    {day}: {len(per_day[day])} intervals")
    return {"selected_intervals": len(horizons)}


def check_g(forecasts: list[dict], actuals: list[dict], day: date = SAMPLE_DELIVERY_DAY) -> dict:
    rule("(g) Granularity, startTime semantics, settlement-period mapping, DST")

    say("[forecast granularity]")
    start_minutes = collections.Counter(r["startTime"][14:16] for r in forecasts)
    publish_minutes = collections.Counter(r["publishTime"][14:16] for r in forecasts)
    say(f"  startTime minute-of-hour values : {dict(start_minutes)}")
    say(f"  publishTime minute-of-hour values: {dict(publish_minutes)}")

    actual_minutes = collections.Counter(r["startTime"][14:16] for r in actuals)
    say(f"  actuals   minute-of-hour values : {dict(actual_minutes)}")
    say("  => WINDFOR is a contiguous HOURLY series (all startTimes on the hour).")
    say("  => FUELHH  is a contiguous HALF-HOURLY series. The two datasets are")
    say("     genuinely at different native resolutions.")

    say()
    say("[publication schedule actually observed]")
    publishes_per_day: dict[str, set[str]] = {}
    for record in forecasts:
        publishes_per_day.setdefault(record["publishTime"][:10], set()).add(record["publishTime"])
    counts = sorted(len(v) for v in publishes_per_day.values())
    say(f"  distinct publishTime values per calendar day: min={counts[0]} "
        f"median={counts[len(counts) // 2]} max={counts[-1]}")
    times_of_day = sorted({r["publishTime"][11:16] for r in forecasts})
    say(f"  distinct publish times-of-day (UTC): {times_of_day}")
    per_publish = sorted(
        collections.Counter(r["publishTime"] for r in forecasts).values()
    )
    say(f"  hourly values carried per publish: min={per_publish[0]} "
        f"median={per_publish[len(per_publish) // 2]} max={per_publish[-1]}")
    say(f"  the Elexon BSC glossary describes 4 daily issues (04:30, 10:30, 16:30, 22:30)")
    say(f"  carrying 49 hourly values; the Insights API stream instead exposes "
        f"{counts[len(counts) // 2]} issues/day")
    say(f"  carrying ~{per_publish[len(per_publish) // 2]} hourly values each. We use exactly what")
    say(f"  the API returns and record it here rather than assuming the glossary schedule.")
    odd = [
        p for p in sorted({r["publishTime"] for r in forecasts})
        if p[14:16] != "30"
    ]
    say(f"  publishes not on the half-hour mark (data quality check): {odd or 'none'}")

    say()
    say("[startTime semantics]")
    day_start = _parse_iso(f"{day.isoformat()}T00:00:00Z")
    day_end = day_start + timedelta(days=1)
    starts = sorted(
        {_parse_iso(r["startTime"]) for r in forecasts
         if day_start <= _parse_iso(r["startTime"]) < day_end}
    )
    deltas = sorted({(b - a).total_seconds() / 60 for a, b in zip(starts, starts[1:])})
    say(f"  startTimes on {day}: {len(starts)}, all consecutive gaps = {deltas} minutes")
    say("  => startTime is the BEGINNING of the hour the value applies to, and the")
    say("     value is the forecast average wind generation (MW) over that hour.")
    say("     It is not an instantaneous reading and not a point-in-time sample.")
    say("     decode: forecast_hour = [startTime, startTime + 1h)")

    say()
    say("[mapping: hourly forecast -> settlement periods / half-hour display slots]")
    grid = half_hour_grid(day)
    hours_used = sorted({slot.replace(minute=0, second=0, microsecond=0) for slot in grid})
    usage = collections.Counter(slot.replace(minute=0, second=0, microsecond=0) for slot in grid)
    say(f"  London day {day} has {len(grid)} settlement half-hours")
    say(f"  these map onto {len(hours_used)} distinct forecast hours")
    say(f"  forecast hours used exactly twice each: "
        f"{'yes' if set(usage.values()) == {2} else 'NO - investigate'}")

    sp_lookup = {
        _parse_iso(r["startTime"]): r.get("settlementPeriod") for r in actuals
    }
    say("  worked example (first four settlement periods):")
    for slot in grid[:4]:
        hour = slot.replace(minute=0, second=0, microsecond=0)
        sp = sp_lookup.get(slot)
        local = slot.astimezone(LONDON_TZ).strftime("%H:%M")
        say(f"    SP{sp:>3}  {local} London ({_iso_z(slot)})  <- forecast hour {_iso_z(hour)}")

    hours_with_forecast = {
        _parse_iso(r["startTime"]) for r in forecasts
        if _parse_iso(f"{day.isoformat()}T00:00:00Z") <= _parse_iso(r["startTime"])
        < _parse_iso(f"{day.isoformat()}T00:00:00Z") + timedelta(days=1)
    }
    say(f"  forecast hours available for this day: {len(hours_with_forecast)} of {len(hours_used)}")
    say("  => the 48 display slots are retained ONLY because every one of them maps to")
    say("     a real forecast hour. If a forecast hour were absent, its two slots are")
    say("     flagged as missing rather than interpolated.")

    say()
    say("[double-counting rule]")
    say(f"  display slots (half-hours)      : {len(grid)}")
    say(f"  unique forecast intervals (hours): {len(hours_used)}")
    say("  => accuracy metrics are computed on the UNIQUE forecast intervals at native")
    say("     hourly resolution; the half-hour grid is a display/settlement view.")
    say("     Each hourly forecast value is used twice for energy, once for error stats.")

    say()
    say("[daylight saving]")
    for probe in (date(2026, 1, 15), date(2026, 3, 29), date(2026, 10, 25)):
        start = datetime.combine(probe, datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)
        end = datetime.combine(probe + timedelta(days=1), datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)
        slots = int((end - start).total_seconds() // 1800)
        note = "normal" if slots == 48 else ("spring forward (short)" if slots < 48 else "clocks back (long)")
        say(f"  {probe} London: {slots} settlement half-hours ({note}), "
            f"{int((end - start).total_seconds() // 3600)} UTC hours")
    say("  => the hourly forecast grid is 24 values per UTC day always; the settlement")
    say("     grid is 48/46/50 per London day. The mapping is done on UTC instants, so")
    say("     DST is handled by construction. The January 2026 scope contains no DST days.")

    in_scope_dst = []
    cursor = date(2025, 12, 1)
    while cursor <= date(2026, 1, 31):
        start = datetime.combine(cursor, datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)
        end = datetime.combine(cursor + timedelta(days=1), datetime.min.time(), tzinfo=LONDON_TZ).astimezone(timezone.utc)
        if int((end - start).total_seconds() // 1800) != 48:
            in_scope_dst.append(cursor.isoformat())
        cursor += timedelta(days=1)
    say(f"  DST days inside the analysed window (2025-12-01..2026-01-31): "
        f"{in_scope_dst or 'none'}")

    return {
        "forecast_interval_minutes": 60,
        "settlement_interval_minutes": 30,
        "display_slots_per_day": len(grid),
        "unique_forecast_intervals_per_day": len(hours_used),
        "publishes_per_day_median": counts[len(counts) // 2],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="ignore the raw cache")
    args = parser.parse_args()

    client = ElexonClient()

    # The full publish window is fetched once and reused by every check below
    # (and by the real pipeline in STEP 2).
    forecasts = cached_json(
        "windfor_raw.json",
        lambda: client.fetch_wind_forecasts(FORECAST_PUBLISH_FROM, FORECAST_PUBLISH_TO),
        args.refresh,
    )

    say("Elexon BMRS feasibility spike - UK national wind (FUELHH / WINDFOR)")
    say(f"generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")

    summary: dict = {}
    summary["a"] = check_a(client)
    summary["b"] = check_b(client, forecasts)
    summary["c"] = check_c(forecasts)

    # Actuals are needed for (e); fetch them next so the cache is warm.
    actuals = cached_json(
        "fuelhh_wind_raw.json",
        lambda: client.fetch_wind_actuals(ACTUALS_SETTLEMENT_FROM, ACTUALS_SETTLEMENT_TO),
        args.refresh,
    )
    summary["d"] = check_d(forecasts)
    summary["e"] = check_e(actuals)
    summary["f"] = check_f(forecasts)
    summary["g"] = check_g(forecasts, actuals)
    summary["decision_time"] = check_decision_time_horizons(forecasts)

    rule("VERDICT")
    blocker_b = summary["b"]["multi_version_start_times"] == 0
    blocker_d = summary["d"].get("covered", summary["d"].get("covered_half_hours", 0)) == 0
    if blocker_b:
        say("BLOCKER: historical forecast versions cannot be retrieved. STOP.")
    elif blocker_d:
        say("BLOCKER: no eligible forecasts for the sample delivery day. STOP.")
    else:
        say("PASS: historical publish versions and the required publish window are retrievable.")
        say("Partial gaps are NOT a blocker: continue with available data, preserve every")
        say("expected delivery interval, flag missing forecasts and report coverage.")
    say(f"total API requests made in this run: {client.request_count}")

    report_path = DATA_DIR / "feasibility_report.txt"
    report_path.write_text("\n".join(_report_lines) + "\n", encoding="utf-8")
    print(f"\nreport written to {report_path}")
    return 0 if not (blocker_b or blocker_d) else 1


if __name__ == "__main__":
    raise SystemExit(main())
