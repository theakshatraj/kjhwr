"""Calibrated uncertainty for the conservative wind indicator.

The indicator is an *empirical* prediction bound built from the historical
distribution of decision-time errors ``E = F - A``:

    lower bound = max(0, F - P90(E))
    upper bound = max(0, F - P10(E))

Because ``E = F - A``, ``A = F - E``: subtracting the *upper* error percentile
gives a *lower* bound on actual wind. Worked check: F = 4,000 MW, P90(E) = +800,
P10(E) = -600 -> lower = 3,200 MW, upper = 4,600 MW.

POOLED CALIBRATION (important limitation)
-----------------------------------------
The indicator pools *every* historical decision-time settlement half-hour into
one error distribution. It is **not** conditioned on forecast horizon, time of
day, or wind level, because that conditioning has not been implemented and
validated here. The resulting coverage is therefore an average across all
intervals; it is not a per-interval or per-horizon guarantee.
``coverage_by_horizon_group`` exists precisely to expose how much the realised
coverage drifts across the horizon groups the pooled distribution is applied to.

LOOK-AHEAD CONTROL
------------------
``strict_no_lookahead=True`` (default) uses only delivery days ``<= D - 2``:
their actuals were fully realised, and published, before the D-1 09:00 cutoff.
``strict_no_lookahead=False`` (retrospective) uses the whole completed month and
is labelled as such - it describes what happened, and is **not** evidence of
decision-time performance.

Coverage is validated out-of-sample only: each day's percentiles are estimated
from eligible prior days, that day's bounds are built from them, and only then
are the bounds compared with that day's actuals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta

import pandas as pd

from app.config import (
    DEFAULT_CUTOFF_TIME,
    DELIVERY_MONTH_END,
    DELIVERY_MONTH_START,
    MIN_CALIBRATION_DAYS,
    MIN_CALIBRATION_INTERVALS,
    TIMEZONE_NAME,
)
from app.services.metrics import horizon_bucket, signed_error_percentiles

MODE_DECISION_TIME = "decision_time"
MODE_RETROSPECTIVE = "retrospective"
CALIBRATION_MODES = (MODE_DECISION_TIME, MODE_RETROSPECTIVE)

#: Nominal one-sided coverage the lower bound targets (P90 of the error).
TARGET_LOWER_COVERAGE = 0.9

#: Returned whenever fewer than ``MIN_CALIBRATION_DAYS`` usable days exist.
INSUFFICIENT_HISTORY = "insufficient calibration history"

POOLED_CALIBRATION_NOTE = (
    "Pooled calibration: every historical decision-time half-hour contributes to one "
    "error distribution. The bound is not conditioned on forecast horizon or time of "
    "day, so the nominal coverage is an average rather than a per-interval guarantee."
)


# ---------------------------------------------------------------------------
# percentiles and the bound formula
# ---------------------------------------------------------------------------
def error_percentiles(errors) -> dict[str, float]:
    """Signed-error percentiles (``p5, p10, p50, p90, p95``).

    Accepts a DataFrame containing ``error_mw``, or any iterable of errors.
    """
    if isinstance(errors, pd.DataFrame):
        series = errors["error_mw"] if "error_mw" in errors.columns else errors.iloc[:, 0]
    else:
        series = errors
    return signed_error_percentiles(series)


def lower_bound(forecast_mw, p90_error):
    """Lower bound on actual wind: ``max(0, F - P90(E))``.

    Worked check: F = 4000, P90(E) = +800 -> 3200 (not 3400).
    """
    if isinstance(forecast_mw, pd.Series):
        return (forecast_mw - p90_error).clip(lower=0.0)
    return max(0.0, float(forecast_mw) - float(p90_error))


def upper_bound(forecast_mw, p10_error):
    """Upper bound on actual wind: ``max(0, F - P10(E))``."""
    if isinstance(forecast_mw, pd.Series):
        return (forecast_mw - p10_error).clip(lower=0.0)
    return max(0.0, float(forecast_mw) - float(p10_error))


# ---------------------------------------------------------------------------
# calibration object
# ---------------------------------------------------------------------------
@dataclass
class Calibration:
    """Pooled signed-error percentiles plus their honest sample sizes."""

    mode: str
    available: bool
    n_days: int
    n_intervals: int
    percentiles: dict[str, float] = field(default_factory=dict)
    reason: str | None = None
    warmup_days: int = 0
    delivery_date: date | None = None
    history_from: date | None = None
    history_to: date | None = None

    @property
    def strict_no_lookahead(self) -> bool:
        return self.mode == MODE_DECISION_TIME

    @property
    def label(self) -> str:
        """Human-readable mode, so retrospective results cannot be misread."""
        if self.mode == MODE_RETROSPECTIVE:
            return "retrospective (whole month; NOT decision-time evidence)"
        return "decision-time (strict, no look-ahead)"

    def lower_offset_mw(self) -> float | None:
        """P90(E): the amount to subtract from F for the lower bound."""
        return self.percentiles.get("p90")

    def upper_offset_mw(self) -> float | None:
        """P10(E): the amount to subtract from F for the upper bound."""
        return self.percentiles.get("p10")

    def bounds(self) -> dict[str, float] | None:
        """The offsets to apply, or ``None`` when the indicator is unavailable."""
        if not self.available:
            return None
        return {
            "lower_offset_mw": self.lower_offset_mw(),
            "upper_offset_mw": self.upper_offset_mw(),
        }


def _history(
    dataset: pd.DataFrame, delivery_date: date, mode: str
) -> tuple[pd.DataFrame, int]:
    """Select the error history the mode allows; count warm-up days used."""
    scored = dataset[dataset["error_mw"].notna()]
    if mode == MODE_RETROSPECTIVE:
        month = scored[
            (scored["delivery_date"] >= DELIVERY_MONTH_START)
            & (scored["delivery_date"] <= DELIVERY_MONTH_END)
        ]
        return month, 0

    # Strict: an error is usable only if its delivery day closed before the
    # decision was made. For a D-1 cutoff that means delivery days <= D-2.
    latest_known = delivery_date - timedelta(days=2)
    usable = scored[scored["delivery_date"] <= latest_known]
    warmup = int(
        usable.loc[usable["delivery_date"] < DELIVERY_MONTH_START, "delivery_date"].nunique()
    )
    return usable, warmup


def _describe(history: pd.DataFrame) -> tuple[date | None, date | None]:
    if history.empty:
        return None, None
    return history["delivery_date"].min(), history["delivery_date"].max()


def calibrate(
    dataset: pd.DataFrame,
    delivery_date: date,
    mode: str = MODE_DECISION_TIME,
) -> Calibration:
    """Pooled percentiles for one decision day, honouring the look-ahead rule."""
    if mode not in CALIBRATION_MODES:
        raise ValueError(f"unknown calibration mode {mode!r}")

    history, warmup = _history(dataset, delivery_date, mode)
    n_days = int(history["delivery_date"].nunique())
    n_intervals = int(history["error_mw"].notna().sum())
    history_from, history_to = _describe(history)

    if n_days < MIN_CALIBRATION_DAYS or n_intervals < MIN_CALIBRATION_INTERVALS:
        return Calibration(
            mode=mode,
            available=False,
            n_days=n_days,
            n_intervals=n_intervals,
            reason=INSUFFICIENT_HISTORY,
            warmup_days=warmup,
            delivery_date=delivery_date,
            history_from=history_from,
            history_to=history_to,
        )

    return Calibration(
        mode=mode,
        available=True,
        n_days=n_days,
        n_intervals=n_intervals,
        percentiles=signed_error_percentiles(history["error_mw"]),
        warmup_days=warmup,
        delivery_date=delivery_date,
        history_from=history_from,
        history_to=history_to,
    )


def calibrated_bounds(
    delivery_date: date,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    strict_no_lookahead: bool = True,
    dataset: pd.DataFrame | None = None,
    tz: str = TIMEZONE_NAME,
) -> Calibration:
    """Calibration for ``delivery_date`` under the requested look-ahead policy.

    ``strict_no_lookahead=True`` uses only delivery days ``<= D - 2`` (including
    the December warm-up). There is deliberately **no** fall-back to future data:
    if fewer than ``MIN_CALIBRATION_DAYS`` usable days exist the result is
    unavailable, ``bounds()`` is ``None``, and the reason is
    ``"insufficient calibration history"``.

    ``strict_no_lookahead=False`` is the retrospective view over the whole month
    and is labelled via :attr:`Calibration.label`.
    """
    mode = MODE_DECISION_TIME if strict_no_lookahead else MODE_RETROSPECTIVE
    if dataset is None:
        from app.services.decision_forecast import get_decision_dataset

        dataset = get_decision_dataset(cutoff, tz)
    return calibrate(dataset, delivery_date, mode)


def apply_bounds(frame: pd.DataFrame, calibration: Calibration) -> pd.DataFrame:
    """Attach ``lower_bound_mw`` / ``upper_bound_mw`` using the calibrated offsets."""
    out = frame.copy()
    offsets = calibration.bounds()
    if offsets is None:
        out["lower_bound_mw"] = float("nan")
        out["upper_bound_mw"] = float("nan")
        return out

    out["lower_bound_mw"] = lower_bound(out["forecast_mw"], offsets["lower_offset_mw"])
    out["upper_bound_mw"] = upper_bound(out["forecast_mw"], offsets["upper_offset_mw"])
    return out


# ---------------------------------------------------------------------------
# out-of-sample coverage validation
# ---------------------------------------------------------------------------
def _out_of_sample_coverage(
    dataset: pd.DataFrame,
    cutoff: time,
    strict_no_lookahead: bool,
    eval_from: date | None,
    eval_to: date | None,
) -> tuple[pd.DataFrame, list[date]]:
    """Score each evaluated day against bounds built from *prior* days only.

    Returns the per-interval coverage frame and the delivery days that were
    skipped because their calibration history was insufficient.
    """
    empty = pd.DataFrame(
        columns=[
            "delivery_date",
            "horizon_hours",
            "actual_mw",
            "lower_bound_mw",
            "upper_bound_mw",
            "covered_lower",
            "covered_band",
            "horizon_bucket",
        ]
    )
    if dataset.empty:
        return empty, []

    frames: list[pd.DataFrame] = []
    excluded: list[date] = []
    for day in sorted(dataset["delivery_date"].unique()):
        if eval_from is not None and day < eval_from:
            continue
        if eval_to is not None and day > eval_to:
            continue
        calibration = calibrated_bounds(
            day, cutoff, strict_no_lookahead, dataset=dataset
        )
        if not calibration.available:
            excluded.append(day)
            continue
        day_frame = dataset[dataset["delivery_date"] == day]
        frames.append(apply_bounds(day_frame, calibration))

    if not frames:
        return empty, excluded

    scored = pd.concat(frames, ignore_index=True)
    scored = scored[
        scored["actual_mw"].notna() & scored["lower_bound_mw"].notna()
    ].copy()
    scored["covered_lower"] = scored["actual_mw"] >= scored["lower_bound_mw"]
    scored["covered_band"] = scored["covered_lower"] & (
        scored["actual_mw"] <= scored["upper_bound_mw"]
    )
    scored["horizon_bucket"] = scored["horizon_hours"].map(horizon_bucket)
    return scored, excluded


def coverage_check(
    dataset: pd.DataFrame,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    strict_no_lookahead: bool = True,
    eval_from: date | None = None,
    eval_to: date | None = None,
) -> dict:
    """Genuinely out-of-sample coverage of the indicator.

    For every evaluated delivery day the error percentiles are estimated from
    eligible *prior* days only, that day's bounds are built from those
    percentiles, and only then are the bounds compared with that day's actuals.
    Percentiles are never estimated and validated on the same observations.

    Reports the number of evaluated intervals **and** days, the observed
    lower-bound coverage (``actual >= lower``) and the observed prediction-band
    coverage (``lower <= actual <= upper``). Days whose calibration history was
    insufficient are excluded and counted.
    """
    scored, excluded = _out_of_sample_coverage(
        dataset, cutoff, strict_no_lookahead, eval_from, eval_to
    )
    n_intervals = int(len(scored))
    n_days = int(scored["delivery_date"].nunique()) if n_intervals else 0

    note = (
        "Out-of-sample: each day's bounds use prior-day errors only. In-sample "
        "coverage is not evidence of predictive coverage."
    )
    if n_days and n_days < 10:
        note += (
            f" Sample is small ({n_days} day(s), {n_intervals} interval(s)); treat the "
            "coverage figures as indicative only."
        )
    if n_days == 0:
        note += " No day had enough prior history to build out-of-sample bounds."

    return {
        "mode": MODE_DECISION_TIME if strict_no_lookahead else MODE_RETROSPECTIVE,
        "strict_no_lookahead": bool(strict_no_lookahead),
        "n_intervals": n_intervals,
        "n_days": n_days,
        "lower_bound_coverage": (
            float(scored["covered_lower"].mean()) if n_intervals else None
        ),
        "band_coverage": float(scored["covered_band"].mean()) if n_intervals else None,
        "target": TARGET_LOWER_COVERAGE,
        "excluded_days": [d.isoformat() for d in excluded],
        "excluded_day_count": len(excluded),
        "note": note,
    }


def coverage_by_horizon_group(
    dataset: pd.DataFrame,
    cutoff: time = DEFAULT_CUTOFF_TIME,
    strict_no_lookahead: bool = True,
    eval_from: date | None = None,
    eval_to: date | None = None,
    material_threshold: float = 0.05,
) -> dict:
    """Out-of-sample lower-bound coverage broken down by forecast-horizon group.

    Decision-time forecasts do not share one horizon: the selected vintage is
    older for later slots of the delivery day. The pooled percentiles are applied
    to all of them, so this breakdown shows whether the nominal coverage actually
    holds in each group. Variation wider than ``material_threshold`` is flagged -
    the pooled bound should not be read as a per-horizon guarantee.
    """
    scored, excluded = _out_of_sample_coverage(
        dataset, cutoff, strict_no_lookahead, eval_from, eval_to
    )

    groups: list[dict] = []
    if not scored.empty:
        grouped = scored.dropna(subset=["horizon_bucket"]).groupby(
            "horizon_bucket", sort=True
        )
        for bucket, chunk in grouped:
            groups.append(
                {
                    "horizon_bucket": str(bucket),
                    "n_intervals": int(len(chunk)),
                    "n_days": int(chunk["delivery_date"].nunique()),
                    "lower_bound_coverage": float(chunk["covered_lower"].mean()),
                }
            )

    coverages = [g["lower_bound_coverage"] for g in groups]
    spread = (max(coverages) - min(coverages)) if len(coverages) > 1 else 0.0
    material = bool(spread > material_threshold)

    note = (
        "Out-of-sample lower-bound coverage per horizon group. The underlying bound is "
        "pooled (not horizon-conditioned), so the nominal 90% does not hold for every "
        "group; the spread below is the observed drift."
    )
    if material:
        note += (
            f" Coverage varies materially across horizon groups (spread "
            f"{spread:.3f} > {material_threshold:.2f})."
        )

    return {
        "mode": MODE_DECISION_TIME if strict_no_lookahead else MODE_RETROSPECTIVE,
        "strict_no_lookahead": bool(strict_no_lookahead),
        "n_intervals": int(len(scored)),
        "n_days": int(scored["delivery_date"].nunique()) if len(scored) else 0,
        "target": TARGET_LOWER_COVERAGE,
        "groups": groups,
        "coverage_spread": spread,
        "material_variation": material,
        "excluded_day_count": len(excluded),
        "note": note,
    }
