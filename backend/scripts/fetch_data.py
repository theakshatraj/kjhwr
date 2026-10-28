"""Phase 1 / STEP 2 - build the offline snapshot.

Fetch (or reuse) the raw Elexon JSON, clean it, write the processed parquet
files and record provenance.

Usage:
    python scripts/fetch_data.py            # reuse raw cache if present
    python scripts/fetch_data.py --refresh  # re-download everything
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import (  # noqa: E402
    ACTUALS_SETTLEMENT_FROM,
    ACTUALS_SETTLEMENT_TO,
    FORECAST_PUBLISH_FROM,
    FORECAST_PUBLISH_TO,
    PROVENANCE_PATH,
    RAW_DIR,
)
from app.services.data_store import (  # noqa: E402
    RAW_ACTUALS_PATH,
    RAW_FORECAST_PATH,
    clean_actuals,
    clean_forecasts,
    write_processed,
    write_provenance,
)
from app.services.elexon_client import ElexonClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch_data")


def _fetch_or_load(path: Path, fetch, refresh: bool, label: str) -> tuple[list[dict], bool]:
    if path.exists() and not refresh:
        records = json.loads(path.read_text(encoding="utf-8"))
        logger.info("%s: reusing cached %s (%s records)", label, path.name, len(records))
        return records, False
    logger.info("%s: downloading ...", label)
    records = fetch()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records), encoding="utf-8")
    logger.info("%s: wrote %s (%s records)", label, path.name, len(records))
    return records, True


def _planned_requests() -> list[dict]:
    """The chunked requests this snapshot corresponds to, cache or not.

    Provenance must describe how the data was obtained even when a run reuses
    the raw cache and makes no HTTP calls at all.
    """
    from app.services.elexon_client import ElexonClient

    client = ElexonClient()
    planned: list[dict] = []
    for start, end in ElexonClient._chunks(FORECAST_PUBLISH_FROM, FORECAST_PUBLISH_TO):
        planned.append(
            {
                "dataset": "WINDFOR",
                "url": f"{client.base_url}/datasets/WINDFOR/stream",
                "params": {"publishDateTimeFrom": start, "publishDateTimeTo": end},
            }
        )
    for start, end in ElexonClient._date_chunks(ACTUALS_SETTLEMENT_FROM, ACTUALS_SETTLEMENT_TO):
        planned.append(
            {
                "dataset": "FUELHH",
                "url": f"{client.base_url}/datasets/FUELHH/stream",
                "params": {
                    "settlementDateFrom": start,
                    "settlementDateTo": end,
                    "fuelType": "WIND",
                },
            }
        )
    return planned


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the processed wind snapshot.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the raw cache and re-download from Elexon",
    )
    args = parser.parse_args()

    client = ElexonClient()

    raw_forecasts, forecasts_fetched = _fetch_or_load(
        RAW_FORECAST_PATH,
        lambda: client.fetch_wind_forecasts(FORECAST_PUBLISH_FROM, FORECAST_PUBLISH_TO),
        args.refresh,
        "WINDFOR",
    )
    raw_actuals, actuals_fetched = _fetch_or_load(
        RAW_ACTUALS_PATH,
        lambda: client.fetch_wind_actuals(ACTUALS_SETTLEMENT_FROM, ACTUALS_SETTLEMENT_TO),
        args.refresh,
        "FUELHH WIND",
    )

    forecasts = clean_forecasts(raw_forecasts)
    actuals = clean_actuals(raw_actuals)

    write_processed(forecasts, actuals)

    if client.request_log:
        api_calls = [
            {**entry, "served_from_cache": False} for entry in client.request_log
        ]
    else:
        api_calls = [
            {**entry, "served_from_cache": True, "rows": None}
            for entry in _planned_requests()
        ]

    provenance = write_provenance(
        raw_forecast_count=len(raw_forecasts),
        raw_actual_count=len(raw_actuals),
        forecasts=forecasts,
        actuals=actuals,
        api_calls=api_calls,
    )

    print()
    print(f"forecasts : {len(forecasts):>7} rows  {forecasts['start_time'].min()} .. {forecasts['start_time'].max()}")
    print(f"actuals   : {len(actuals):>7} rows  {actuals['start_time'].min()} .. {actuals['start_time'].max()}")
    print(f"actuals gaps: {provenance['coverage']['actuals_missing_intervals']}")
    print(f"api requests: {client.request_count} (downloaded this run: forecasts={forecasts_fetched} actuals={actuals_fetched})")
    print(f"provenance : {PROVENANCE_PATH}")
    for step in provenance["cleaning_steps"]:
        print(f"  - {step}")
    print("\nSnapshot written. Next: python scripts/validate_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
