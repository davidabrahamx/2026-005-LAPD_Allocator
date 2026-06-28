"""Aggregation + 1-week-ahead seasonal forecast (docs/03 STEP 5).

Forecast = linear trend x multiplicative week-of-year seasonal index. The seasonal index is
estimated by ratio-to-trend over the 2-year window, so recurring holiday weeks (e.g. Jul-4 ~=
ISO W27, Thanksgiving ~= W47-48, Christmas/New-Year ~= W52/W01) raise or lower the prediction.
With <1 full year (no repeated week-of-year) the factor defaults to 1.0 -> pure trend, which is
why the deterministic sample gate (docs/00) is unchanged.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.config import SEVERITY_WEIGHTS


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly incidence + severity-weighted magnitude per (area, category).

    `incidence` sums the call count `n`; `magnitude` sums severity-weighted counts.
    `iso_week` is already present from ingest.
    """
    df = df.copy()
    df["sev_n"] = df["severity"] * df["n"]
    agg = (
        df.groupby(["area_occ", "category", "iso_week"])
        .agg(incidence=("n", "sum"), magnitude=("sev_n", "sum"))
        .reset_index()
    )
    return agg


def _week_of_year(label: str) -> int:
    """'YYYY-Www' -> ISO week number (1..53)."""
    return int(label.split("-W")[1])


def _next_week_of_year(last_label: str) -> int:
    """ISO week-of-year of the week immediately AFTER `last_label` (handles year rollover)."""
    yr, wk = last_label.split("-W")
    monday = date.fromisocalendar(int(yr), int(wk), 1)
    return (monday + timedelta(days=7)).isocalendar().week


def _seasonal_index(y: np.ndarray, trend_fit: np.ndarray, woy: np.ndarray) -> dict:
    """Multiplicative week-of-year factors via ratio-to-trend, normalized to mean 1.

    Returns {week_of_year: factor}; empty if the trend is unusable (≤0 everywhere), so the
    caller degrades to trend-only. Averaging the ratio across years captures recurring
    holiday-week effects.
    """
    ratios = np.divide(y, trend_fit, out=np.full_like(y, np.nan, dtype=float),
                       where=trend_fit > 0)
    factors = {}
    for w in np.unique(woy):
        vals = ratios[(woy == w) & np.isfinite(ratios)]
        if vals.size:
            factors[int(w)] = float(vals.mean())
    if not factors:
        return {}
    mean_f = float(np.mean(list(factors.values())))
    if mean_f <= 0:
        return {}
    return {w: f / mean_f for w, f in factors.items()}  # mean factor == 1 (redistribute only)


def forecast(agg: pd.DataFrame) -> pd.DataFrame:
    """Predict next week's incidence per (area, category): linear trend × seasonal index."""
    rows = []
    for (area, cat), series in agg.groupby(["area_occ", "category"]):
        series = series.sort_values("iso_week")
        weeks = series["iso_week"].tolist()
        y = series["incidence"].to_numpy(dtype=float)
        k = len(y)
        if k >= 3:
            x = np.arange(k)
            slope, intercept = np.polyfit(x, y, 1)
            trend_fit = slope * x + intercept            # fitted trend per observed week
            trend_next = slope * k + intercept           # deseasonalized level for next week
            woy = np.array([_week_of_year(w) for w in weeks])
            season = _seasonal_index(y, trend_fit, woy)  # {week_of_year: factor}, mean≈1
            factor = season.get(_next_week_of_year(weeks[-1]), 1.0)  # 1.0 if week-of-year unseen
            yhat = max(0.0, trend_next * factor)
            trend = "up" if slope > 0.5 else "down" if slope < -0.5 else "flat"
        else:
            yhat = float(y.mean()) if k else 0.0
            trend = "flat"
        rows.append({
            "area_occ": area,
            "category": cat,
            "forecast_incidence": round(yhat, 1),
            "trend": trend,
            "severity": SEVERITY_WEIGHTS.get(cat, 1),
        })
    return pd.DataFrame(rows)


def weekly_incidence(area: str, agg: pd.DataFrame) -> pd.DataFrame:
    """Helper for the UI trend chart: total weekly incidence for one area."""
    sub = agg[agg["area_occ"] == area]
    return (sub.groupby("iso_week")["incidence"].sum()
            .reset_index(name="incidence"))


def weekly_totals(agg: pd.DataFrame) -> pd.DataFrame:
    """Citywide weekly incidence totals (for the trend KPI / chart)."""
    return (agg.groupby("iso_week")["incidence"].sum()
            .reset_index(name="incidence").sort_values("iso_week"))


def area_priority(fc: pd.DataFrame) -> pd.DataFrame:
    """Rank areas by severity-weighted forecast priority (shared by UI + allocation).

    Returns columns: area_occ, priority_index, top_category, rank (1 = highest).
    `priority_index` is a relative 0–100 score (100 = the highest-priority area), so it is
    interpretable at a glance; because it is a linear scaling of the raw priority, the unit
    apportionment is unchanged by the normalization. Independent of the unit pool, so the
    dashboard can show priority before the planner confirms deployable units.
    """
    cols = ["area_occ", "priority_index", "top_category", "rank"]
    if fc.empty:
        return pd.DataFrame(columns=cols)
    fc = fc.copy()
    fc["priority"] = fc["forecast_incidence"] * fc["severity"]
    by_area = (fc.groupby("area_occ")["priority"].sum()
               .reset_index(name="priority_raw"))
    top = (fc.sort_values("priority", ascending=False)
           .groupby("area_occ").first()["category"]
           .reset_index(name="top_category"))
    by_area = by_area.merge(top, on="area_occ", how="left")
    by_area = by_area.sort_values("priority_raw", ascending=False).reset_index(drop=True)
    peak = by_area["priority_raw"].max()
    by_area["priority_index"] = (100 * by_area["priority_raw"] / peak).round(1) if peak > 0 else 0.0
    by_area["rank"] = by_area.index + 1
    return by_area[cols]
