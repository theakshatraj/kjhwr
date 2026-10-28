"""Central configuration for the wind forecast decision portal.

All constants that describe *what* data we analyse live here so the API,
pipeline and tests cannot drift apart.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
PROVENANCE_PATH = DATA_DIR / "provenance.json"

# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------
LONDON_TZ = ZoneInfo("Europe/London")
UTC_TZ = ZoneInfo("UTC")

#: Delivery days are London calendar days.
TIMEZONE_NAME = "Europe/London"

#: Assumed decision cutoff (local London time on delivery day - 1).
#: This is an *assumption*, not an official gate closure. The real day-ahead
#: auction gate closure differs by exchange (Nord Pool documentation reportedly
#: lists 09:50 GMT for N2EX) - confirm with the team.
DEFAULT_CUTOFF_TIME = time(9, 0)
#: The same cutoff as an ``HH:MM`` string, for query defaults and display.
DEFAULT_CUTOFF_LOCAL_TIME = DEFAULT_CUTOFF_TIME.strftime("%H:%M")

# --------------------------------------------------------------------------
# Analysis scope
# --------------------------------------------------------------------------
#: Delivery month in scope for the decision-time analysis.
DELIVERY_MONTH_START = date(2026, 1, 1)
DELIVERY_MONTH_END = date(2026, 1, 31)

#: Actuals (FUELHH) window - includes the December warm-up period.
#: FUELHH is filtered on *settlement date* (a London calendar date).
ACTUALS_SETTLEMENT_FROM = "2025-12-01"
ACTUALS_SETTLEMENT_TO = "2026-01-31"

#: Forecasts (WINDFOR) window, filtered on publish time.
#: Starts 2025-11-30 so that 1 December decisions can be reconstructed, and so
#: the January delivery days have a seeded December calibration history.
FORECAST_PUBLISH_FROM = "2025-11-30T00:00:00Z"
FORECAST_PUBLISH_TO = "2026-01-31T00:00:00Z"

#: Minimum history required before the conservative-wind indicator is shown.
MIN_CALIBRATION_DAYS = 7
MIN_CALIBRATION_INTERVALS = 336  # 7 days * 48 half-hour intervals

# --------------------------------------------------------------------------
# Sources / attribution
# --------------------------------------------------------------------------
ELEXON_BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"

SOURCE_ATTRIBUTION = (
    "Contains data from Elexon Insights Solution / BMRS "
    "(https://bmrs.elexon.co.uk), licensed under the Elexon Open Data Licence. "
    "Data is used for historical analysis only."
)

SNAPSHOT_CAVEAT = (
    "This portal is a fixed historical analysis snapshot, not a live trading "
    "system. Nothing here is a procurement recommendation."
)


def decision_cutoff_utc(
    delivery_date: date,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    tz: str = TIMEZONE_NAME,
):
    """Return the UTC instant of the assumed decision cutoff for `delivery_date`.

    The cutoff falls on the day *before* delivery, at `cutoff` local time in
    `tz`. Europe/London is GMT (UTC+0) for the January 2026 scope, but the
    conversion is done properly so the code is correct for any date - including
    the DST transitions.
    """
    local_dt = datetime.combine(delivery_date - timedelta(days=1), cutoff, tzinfo=ZoneInfo(tz))
    return local_dt.astimezone(UTC_TZ)
