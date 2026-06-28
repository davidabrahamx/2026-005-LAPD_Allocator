"""Data ingestion: live Socrata SODA call with rolling-snapshot + CSV fallback (docs/03 STEP 3).

The live query aggregates **server-side** to (area, call type, ISO week) with counts over a
TWO-YEAR window, so the forecast's week-of-year seasonal index can model recurring holiday
weeks. The current, in-progress ISO week is dropped (see `_finish`) so a partial week never
skews the trend. Every successful
pull is saved to `LAST_GOOD_CSV`; on any failure we fall back to that most-recent snapshot,
and only if it is missing to the bundled `SAMPLE_CSV`. Resilience & validation per docs/05
(EH-2, IV-1, T2): `days` is coerced/clamped before the query, and every failure degrades to a
logged fallback rather than raising.
"""
import logging
import os
from datetime import date, timedelta

import pandas as pd
import requests

from app.config import (LAST_GOOD_CSV, LOOKBACK_DAYS, NORMALIZED_COLUMNS,
                        SAMPLE_CSV, SODA_ENDPOINT)

logger = logging.getLogger(__name__)


def load_calls(days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Return trailing `days` of calls, normalized to (area, call type, ISO week, n).

    Tries the live Socrata API (server-side weekly aggregation) over a 2-year window; on
    success it rewrites the rolling fallback snapshot. On any error it falls back to the most
    recent snapshot, then to the bundled sample CSV, then to an empty frame. The current
    in-progress ISO week is excluded in `_finish`. Never raises.
    """
    days = max(1, min(int(days), 800))  # IV-1: validate/clamp (admit the 2-year window)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    params = {
        # Aggregate server-side: count per (area, call type, year, ISO week).
        "$select": ("area_occ, call_type_code, call_type_text, "
                    "date_extract_y(dispatch_date) AS yr, "
                    "date_extract_woy(dispatch_date) AS wk, count(1) AS n"),
        "$where": f"dispatch_date >= '{cutoff}'",  # cutoff is a server-derived date (T2)
        "$group": "area_occ, call_type_code, call_type_text, yr, wk",
        "$limit": 500000,  # 2-year weekly aggregate is far larger than the 90-day one
    }
    try:
        resp = requests.get(SODA_ENDPOINT, params=params, timeout=60)
        resp.raise_for_status()
        df = pd.DataFrame(resp.json())
        if df.empty:
            raise ValueError("empty result from Socrata")
        df = _from_aggregated(df)
        _save_last_good(df)  # refresh the rolling fallback on every successful pull
        source = "Socrata live API (2y weekly aggregate)"
    except Exception as e:
        logger.warning("Socrata fetch failed (%s); using last good snapshot/sample", e)
        df, source = _load_fallback(cutoff)

    df.attrs["source"] = source
    return df


def _save_last_good(df: pd.DataFrame) -> None:
    """Persist the latest successful (normalized) pull as the rolling fallback. Best-effort."""
    try:
        os.makedirs(os.path.dirname(LAST_GOOD_CSV), exist_ok=True)
        df.to_csv(LAST_GOOD_CSV, index=False)
    except Exception as e:
        logger.warning("could not update last-good snapshot (%s)", e)


def _load_fallback(cutoff: str):
    """Offline fallback: most recent live snapshot first, else the bundled sample CSV.

    Returns (DataFrame, source-label). Never raises.
    """
    try:
        if os.path.exists(LAST_GOOD_CSV):
            snap = pd.read_csv(LAST_GOOD_CSV, dtype=str)
            snap["n"] = pd.to_numeric(snap.get("n"), errors="coerce").fillna(0).astype(int)
            return _finish(snap), "last good snapshot (offline fallback)"
    except Exception as e:
        logger.warning("last-good snapshot unusable (%s); using bundled sample", e)
    try:
        raw = pd.read_csv(SAMPLE_CSV, dtype=str)
        if "dispatch_date" in raw.columns:
            raw = raw[raw["dispatch_date"] >= cutoff]
        return _from_raw(raw), "bundled sample CSV (cold-start fallback)"
    except Exception as e2:
        logger.error("Sample CSV unavailable (%s); returning empty dataset", e2)
        return pd.DataFrame(columns=NORMALIZED_COLUMNS), "empty (no data source)"


def _from_aggregated(df: pd.DataFrame) -> pd.DataFrame:
    """Live path: server already grouped to (area, code, text, yr, wk) with count n."""
    df = df.copy()
    df["iso_week"] = (df["yr"].astype(int).astype(str) + "-W"
                      + df["wk"].astype(int).map("{:02d}".format))
    df["n"] = pd.to_numeric(df["n"], errors="coerce").fillna(0).astype(int)
    return _finish(df)


def _from_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback path: raw one-row-per-incident CSV; derive ISO week, set n=1."""
    df = df.copy()
    for col in ("area_occ", "call_type_code", "call_type_text", "dispatch_date"):
        if col not in df.columns:
            df[col] = ""
    df["iso_week"] = pd.to_datetime(df["dispatch_date"], errors="coerce").dt.strftime("%G-W%V")
    df["n"] = 1
    return _finish(df)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    """Shared normalization → guarantees NORMALIZED_COLUMNS (docs/05 IV-3)."""
    for col in ("area_occ", "call_type_code", "call_type_text"):
        if col not in df.columns:
            df[col] = ""
    df["area_occ"] = df["area_occ"].astype(str).str.strip()
    df["call_type_text"] = df["call_type_text"].fillna("").astype(str).str.upper()
    df["call_type_code"] = df["call_type_code"].fillna("").astype(str).str.upper()
    df = df.dropna(subset=["iso_week"])
    df = df[df["area_occ"].str.len() > 0]
    current_week = date.today().strftime("%G-W%V")  # ISO week rolls over Monday 00:00
    df = df[df["iso_week"] != current_week]          # drop the in-progress week
    return df[NORMALIZED_COLUMNS].reset_index(drop=True)
