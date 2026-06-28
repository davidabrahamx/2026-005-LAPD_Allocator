# 4. File Contents (verbatim, authoritative)

Authoritative bytes. For each `### File: <path>` block, write the fenced content to `<path>` EXACTLY —
no reformat, rename, "improve", or extra files. Authoritative over `docs/03` for file contents.

## Manifest (create in this order)

- `app/__init__.py`
- `app/config.py`
- `app/db.py`
- `app/ingest.py`
- `app/categorize.py`
- `app/analyze.py`
- `app/suggest.py`
- `app/app.py`
- `verify.py`
- `tests/__init__.py`
- `tests/test_pipeline.py`
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `.streamlit/config.toml`
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
- `run_app.ps1`
- `run_app.sh`
- `install.ps1`
- `launch.py`
- `Start_LAPD_Advisor.cmd`
- `data/sample_calls.csv`

---

### File: `app/__init__.py`

```python
"""LAPD Resource Allocation Advisor application package."""
```

### File: `app/config.py`

```python
"""Central configuration: all tunables live here (see docs/03 STEP 1).

Nothing else in the app should hard-code a dataset id, weight, or threshold.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

# --- Logging (see docs/05 §5.2). Entry points call configure_logging() once. ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def configure_logging() -> None:
    """Configure root logging once (idempotent). Called by app.py and verify.py."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

# --- AI provider (Gemini today; swap only suggest.generate_text for others) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Current stable Flash tier. Alternatives via the GEMINI_MODEL env var:
#   gemini-flash-latest  -> auto-tracks the newest Flash (changes with ~2-week notice)
#   gemini-3.5-flash     -> same model, pinned version name
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# --- Data source: LAPD Calls for Service 2024-Present (Socrata SODA) ---
DATASET_ID = "xjgu-z4ju"
SODA_ENDPOINT = f"https://data.lacity.org/resource/{DATASET_ID}.json"
# Two full years (~104 ISO weeks) so the forecast's week-of-year seasonal index sees each
# holiday week in >=2 years and can adjust for it. The current in-progress ISO week is dropped
# in ingest._finish so a partial week never skews the fit; ingest.load_calls lifts its day cap.
LOOKBACK_DAYS = 730  # "last 2 years" (seasonality-aware)

# --- Allocation ---
# Deployable patrol units to distribute across the 21 LAPD areas for the planning
# watch. This is an OPERATIONAL INPUT the department sets each week (it varies with
# overtime, leave, and events) and is NOT in the public dataset. ~300 is a realistic
# watch-level placeholder; the allocation is proportional, so this value only scales
# the output — it does not change the area ranking. Override it in the UI per run.
TOTAL_PATROL_UNITS = 300

# --- Local paths ---
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DB_PATH = os.path.join(_ROOT, "lapd_cache.sqlite")
# Bundled, version-controlled cold-start sample (raw one-row-per-incident).
SAMPLE_CSV = os.path.join(_ROOT, "data", "sample_calls.csv")
# Rolling snapshot of the most recent SUCCESSFUL live pull (already normalized). Rewritten on
# every successful refresh and used as the offline fallback BEFORE SAMPLE_CSV, so the fallback
# always reflects the last good data (see ingest.load_calls).
LAST_GOOD_CSV = os.path.join(_ROOT, "data", "last_good_calls.csv")

# --- Crime taxonomy ---
# Categories are derived from the LAPD Calls-for-Service vocabulary, which mixes
# radio codes (e.g. "415", "620", "906", "CODE 6") with penal codes and plain text.
VIOLENT = "VIOLENT"
DOMESTIC = "DOMESTIC"
PROPERTY = "PROPERTY"
VICE_NARCOTICS = "VICE_NARCOTICS"
DISTURBANCE = "DISTURBANCE"
TRAFFIC = "TRAFFIC"
ALARM = "ALARM"
MEDICAL_WELFARE = "MEDICAL_WELFARE"
PROACTIVE = "PROACTIVE"  # CODE 6: officer-initiated field investigation, not a crime report
OTHER = "OTHER"

# Severity drives both `magnitude` and the allocation priority (see analyze.area_priority).
# PROACTIVE has weight 0 by design: it is shown for context but EXCLUDED from the
# resource-allocation priority (it is officer activity, not citizen-reported crime).
SEVERITY_WEIGHTS = {
    VIOLENT: 5,
    DOMESTIC: 4,
    PROPERTY: 3,
    VICE_NARCOTICS: 3,
    DISTURBANCE: 2,
    TRAFFIC: 2,
    ALARM: 1,
    MEDICAL_WELFARE: 1,
    PROACTIVE: 0,
    OTHER: 1,
}

# Ordered rules; FIRST MATCH WINS. Tokens are matched as uppercased substrings against
# (call_type_text + " " + call_type_code). Order encodes precedence: an actual violence
# code (242/245) outranks the "domestic" context, a real crime outranks a medical assist,
# and officer-initiated CODE 6 is captured before anything else.
CATEGORY_RULES = [
    # Officer-initiated activity (largest single value ~46%); not a citizen crime call.
    (PROACTIVE, ["CODE 6", "BACK-UP", "990"]),
    # Violent / weapons / threats.
    (VIOLENT, ["187", "211", "245", "242", "243", "246", "261", "207", "209",
               "422", "417", "ADW", "ROBBERY", "BATTERY", "SHOTS", "SHOOTING",
               "STABBING", "RAPE", "KIDNAP", "CRIMINAL THREATS", "WEAPON",
               "GUN", "KNIFE"]),
    # Domestic / family violence and disputes (penal 273.5; radio 620 + family text).
    (DOMESTIC, ["DOM VIOL", "273.5", "CHILD ABUSE", "SPOUSE", "620 FAMILY",
                "FAMILY", "DOMESTIC"]),
    # Property crime.
    (PROPERTY, ["459", "484", "487", "488", "594", "10851", "503", "BURGLARY",
                "THEFT", "STOLEN", "GTA", "VANDAL", "SHOPLIFT", "PROWLER"]),
    # Vice / narcotics / sex offenses (288 = lewd acts w/ child).
    (VICE_NARCOTICS, ["314", "288", "647B", "11350", "11377", "NARCO", "DRUGS",
                      "PROSTITUT", "INDECENT", "LEWD"]),
    # Medical / mental-health / welfare assists.
    (MEDICAL_WELFARE, ["AMB", "O/D", "OVERDOSE", "SUICIDE", "MENTAL", "5150",
                       "918", "WELFARE", "PERSON DOWN", "SICK", "INJURED",
                       "D/B", "DEAD BODY"]),
    # Traffic.
    (TRAFFIC, ["TRAFFIC", "T/C", "DUI", "COLLISION", "23152", "20002",
               "HIT AND RUN", "HIT/RUN", "H & R", "H&R"]),
    # Alarms.
    (ALARM, ["906", "RINGER", "ALARM", "CODE 30"]),
    # Disturbances / quality-of-life / non-family disputes (incl. generic 620).
    (DISTURBANCE, ["415", "507", "921", "620", "390", "DISTURB", "PARTY", "NOISE",
                   "TRESPASS", "PROWL", "LOUD", "NEIGHBOR", "DRINK", "DRUNK", "647"]),
]
DEFAULT_CATEGORY = OTHER

SOURCE_COLUMNS = [
    "incident_number", "area_occ", "rpt_dist", "dispatch_date",
    "dispatch_time", "call_type_code", "call_type_text",
]

# Internal normalized shape (after ingest): one row per (area, call type, ISO week)
# with a count `n`. This lets the live query aggregate server-side and still cover the
# full window without hitting the row cap.
NORMALIZED_COLUMNS = ["area_occ", "call_type_code", "call_type_text", "iso_week", "n"]

# --- Branding ---
# The header is intentionally TEXT-ONLY (no emblem/logo/seal image). Official seals are
# protected insignia, and a generated placeholder looks off — so the UI shows a clean typeset
# title instead. This also keeps the app fully offline (no image fetch at startup).
```

### File: `app/db.py`

```python
"""SQLite result cache keyed by ISO week (see docs/03 STEP 2).

Caching is best-effort (docs/05 EH-3): any SQLite error is logged and swallowed so a cache
problem can never break the app.
"""
import io
import logging
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd

from app.config import DB_PATH

logger = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            key        TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_cache(key: str):
    """Return the cached DataFrame for `key`, or None on miss/any error (best-effort)."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT payload FROM cache WHERE key = ?", (key,)).fetchone()
        conn.close()
        if not row:
            return None
        # pandas 3.x needs a file-like object; a literal JSON string is read as a path.
        return pd.read_json(io.StringIO(row[0]))
    except Exception as e:
        logger.warning("cache read failed for %s: %s", key, e)
        return None


def set_cache(key: str, df: pd.DataFrame) -> None:
    """Write-through cache (parameterized SQL). Errors are logged and swallowed."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO cache(key, payload, created_at) VALUES(?, ?, ?)",
            (key, df.to_json(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("cache write failed for %s: %s", key, e)


def current_week_key(prefix: str = "plan") -> str:
    # %G-W%V == ISO year and ISO week number, e.g. "2026-W26"
    return f"{prefix}:{date.today().strftime('%G-W%V')}"
```

### File: `app/ingest.py`

```python
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
```

### File: `app/categorize.py`

```python
"""Rule-based crime categorization (docs/03 STEP 4). Deterministic, no AI."""
import pandas as pd

from app.config import (CATEGORY_RULES, DEFAULT_CATEGORY, SEVERITY_WEIGHTS)


def classify_row(text: str, code: str):
    """Return (category, severity). First matching rule wins."""
    haystack = f"{text} {code}"
    for category, tokens in CATEGORY_RULES:
        if any(token in haystack for token in tokens):
            return category, SEVERITY_WEIGHTS[category]
    return DEFAULT_CATEGORY, SEVERITY_WEIGHTS[DEFAULT_CATEGORY]


def categorize(df: pd.DataFrame) -> pd.DataFrame:
    """Attach category + severity. Classifies only the DISTINCT (text, code) pairs
    (hundreds) and merges back, instead of running the rules on every row (tens of
    thousands) — the call-type vocabulary is small, so this is a large speedup.
    """
    df = df.copy()
    keys = df[["call_type_text", "call_type_code"]].drop_duplicates()
    classed = keys.apply(
        lambda r: classify_row(r["call_type_text"], r["call_type_code"]),
        axis=1, result_type="expand",
    )
    keys = keys.assign(category=classed[0], severity=classed[1].astype(int))
    return df.merge(keys, on=["call_type_text", "call_type_code"], how="left")
```

### File: `app/analyze.py`

```python
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
```

### File: `app/suggest.py`

```python
"""Deterministic allocation + AI narrative (docs/03 STEP 6).

The ONLY Gemini-aware code is `generate_text`. Swap that one function to target
Anthropic or OpenAI; everything else is provider-agnostic.
"""
import logging

import pandas as pd

from app import analyze
from app.config import GEMINI_API_KEY, GEMINI_MODEL, TOTAL_PATROL_UNITS

logger = logging.getLogger(__name__)


# --- 6a. Deterministic allocation -------------------------------------------
def allocate(fc: pd.DataFrame, total_units: int = TOTAL_PATROL_UNITS) -> pd.DataFrame:
    """Apportion `total_units` across areas by severity-weighted forecast priority.

    Builds on the shared `analyze.area_priority` ranking, then apportions the
    integer unit pool by the largest-remainder method.
    """
    total_units = max(0, int(total_units))  # IV-2: positive int; guards divide-by-zero
    by_area = analyze.area_priority(fc)
    cols = ["rank", "area_occ", "top_category", "priority_index", "recommended_units"]
    if by_area.empty:
        by_area["recommended_units"] = pd.Series(dtype=int)
        return by_area[cols]
    by_area["recommended_units"] = _largest_remainder(
        by_area["priority_index"], total_units)
    return by_area[cols]


def _largest_remainder(weights: pd.Series, total_units: int) -> pd.Series:
    """Apportion `total_units` integers proportional to `weights` (Hamilton method).

    Guarantees the result sums exactly to `total_units` and never gives a
    higher-weighted area fewer units than a lower-weighted one.
    """
    total_w = weights.sum()
    if total_w <= 0:
        return pd.Series([0] * len(weights), index=weights.index)
    quota = total_units * weights / total_w
    floors = quota.apply(int)
    remainder = int(total_units - floors.sum())
    # hand out the leftover units to the largest fractional parts
    fractions = (quota - floors).sort_values(ascending=False)
    for idx in fractions.index[:remainder]:
        floors.at[idx] += 1
    return floors.astype(int)


# --- 6b. AI adapter boundary -------------------------------------------------
def generate_text(system: str, prompt: str) -> str:
    """Provider seam. Only this function knows about Gemini."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.3,
        ),
    )
    return resp.text


def narrative(plan_df: pd.DataFrame) -> str:
    system = (
        "You are a police resource-deployment analyst. Be concise, factual, and "
        "non-discriminatory. Recommend only at the AREA level; never target "
        "individuals or demographics."
    )
    prompt = (
        "Given this ranked weekly allocation table (JSON):\n"
        + plan_df.to_json(orient="records")
        + "\n\nWrite a weekly deployment plan: 3-5 bullet priorities. Each bullet names "
        "the area, its top crime category, and the recommended unit count. End with one "
        "short caveat about data limitations (calls-for-service != confirmed crime)."
    )
    try:
        return generate_text(system, prompt)
    except Exception as e:
        logger.warning("Gemini narrative failed (%s); using deterministic template", e)
        return _template_narrative(plan_df)


def _template_narrative(plan_df: pd.DataFrame) -> str:
    """Deterministic fallback used when no AI key / AI call fails."""
    lines = ["**Weekly deployment plan (template — no AI key configured):**", ""]
    for _, r in plan_df.head(5).iterrows():
        lines.append(
            f"- **{r['area_occ']}** (rank {r['rank']}): focus **{r['top_category']}**; "
            f"deploy **{r['recommended_units']}** units "
            f"(priority index {r['priority_index']}/100)."
        )
    lines += ["",
              "_Caveat: figures are derived from LAPD calls for service, which reflect "
              "reported activity and dispatch volume, not confirmed crimes._"]
    return "\n".join(lines)
```

### File: `app/app.py`

```python
"""Streamlit UI / entry point (docs/03 STEP 7).

Run with:  streamlit run app/app.py

Two-phase design:
  * TREND ANALYSIS (ingest -> categorize -> aggregate -> forecast) runs AUTOMATICALLY
    from the live Socrata query.
  * RESOURCE ALLOCATION requires the planner to CONFIRM the deployable patrol units
    before the plan + AI narrative are produced.
"""
import logging
import os
import sys
from datetime import date

# Allow `streamlit run app/app.py` to resolve the `app` package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import altair as alt
import pandas as pd
import streamlit as st

from app import analyze, categorize, config, db, ingest, suggest
from app.config import LOOKBACK_DAYS, PROACTIVE, TOTAL_PATROL_UNITS, VIOLENT

config.configure_logging()
logger = logging.getLogger(__name__)

NAVY = "#0b2a4a"
GOLD = "#c8a24a"


def _inject_css() -> None:
    st.markdown(
        f"""<style>
        .block-container {{ padding-top: 1.6rem; max-width: 1200px; }}
        [data-testid="stMetric"] {{
            background: #f6f8fb; border: 1px solid #e3e8ef;
            border-radius: 10px; padding: 14px 18px;
        }}
        [data-testid="stMetricValue"] {{ color: {NAVY}; font-weight: 700; }}
        [data-testid="stMetricLabel"] p {{ color: #5b6b80; }}
        h1, h2, h3 {{ color: {NAVY}; }}
        hr {{ border-color: {GOLD}; }}
        </style>""",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Charts (Altair — labeled axes, titles, tooltips)
# --------------------------------------------------------------------------- #
def _hbar(df: pd.DataFrame, x: str, y: str, xt: str, yt: str, title: str):
    return (
        alt.Chart(df)
        .mark_bar(color=NAVY, cornerRadiusEnd=3)
        .encode(
            x=alt.X(f"{x}:Q", title=xt),
            y=alt.Y(f"{y}:N", sort="-x", title=yt),
            tooltip=list(df.columns),
        )
        .properties(title=title, height=max(140, 30 * len(df)))
    )


def _category_mix(crime_df: pd.DataFrame) -> pd.DataFrame:
    """Calls per category (summing counts), sorted descending."""
    return (crime_df.groupby("category")["n"].sum()
            .reset_index(name="calls").sort_values("calls", ascending=False))


def _line(df: pd.DataFrame, title: str):
    return (
        alt.Chart(df)
        .mark_line(point=True, color=NAVY, strokeWidth=2)
        .encode(
            x=alt.X("iso_week:N", title="ISO week"),
            y=alt.Y("incidence:Q", title="Calls"),
            tooltip=["iso_week", "incidence"],
        )
        .properties(title=title, height=280)
    )


# --------------------------------------------------------------------------- #
# Pipeline (Phase 1 — automated, cached)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def run_analysis(days: int, iso_week: str):
    # `iso_week` is a cache-key input ONLY: ISO weeks roll over Monday 00:00, so when a new
    # week starts the key changes and the data is re-pulled automatically (see main()).
    raw = ingest.load_calls(days)
    cat = categorize.categorize(raw)
    agg = analyze.aggregate(cat)
    fc = analyze.forecast(agg)
    return raw, cat, agg, fc


@st.fragment(run_every="1h")
def _weekly_auto_refresh():
    """Heartbeat so an idle, always-on server refreshes at the Monday 00:00 rollover with no
    visitor: hourly it checks the ISO week and, on change, clears the cache and reruns the
    whole app, which re-pulls Socrata and rewrites the fallback snapshot."""
    wk = date.today().strftime("%G-W%V")
    prev = st.session_state.get("analysis_week")
    st.session_state["analysis_week"] = wk
    if prev is not None and prev != wk:
        run_analysis.clear()
        st.rerun(scope="app")


# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="LAPD Resource Allocation Advisor",
                       page_icon="🛡️", layout="wide")
    _inject_css()

    # --- Header (text only; no emblem/logo by design) ---
    st.markdown("###### LOS ANGELES POLICE DEPARTMENT")
    st.markdown("## Resource Allocation Advisor")
    st.markdown("<hr>", unsafe_allow_html=True)

    # --- Sidebar ---
    st.sidebar.header("Analysis settings")
    # Default = 2 years (seasonality); stepped in 10-day increments.
    days = st.sidebar.slider("Analysis window (days)", 90, 760, LOOKBACK_DAYS, step=10)
    if st.sidebar.button("🔄 Refresh data", width="stretch"):
        run_analysis.clear()
    st.sidebar.caption("Auto-refreshes every Monday 00:00; Refresh forces an immediate pull.")

    # ISO week (Monday-anchored) drives the automatic weekly refresh.
    iso_week = date.today().strftime("%G-W%V")
    _weekly_auto_refresh()

    # --- Phase 1: automated analysis ---
    try:
        with st.spinner("Loading and analyzing calls for service…"):
            raw, cat, agg, fc = run_analysis(days, iso_week)
    except Exception as e:  # EH-5
        st.error(f"Analysis could not be completed: {e}")
        st.stop()

    if len(raw) == 0:
        st.warning("No calls returned for this window (live source and sample both empty). "
                   "Try a wider window or check connectivity.")
        st.stop()

    st.sidebar.caption(f"Data source: {raw.attrs.get('source', 'unknown')}")
    st.sidebar.caption(f"Window: last {days} days · {len(raw):,} calls")

    crime = cat[cat["category"] != PROACTIVE]
    priority = analyze.area_priority(fc)

    tab_overview, tab_trends, tab_alloc = st.tabs(
        ["📊 Overview", "📈 Crime trends", "🚔 Resource allocation"])

    # ===================== OVERVIEW =====================
    with tab_overview:
        total_calls = int(cat["n"].sum())
        crime_calls = int(crime["n"].sum())
        violent_calls = int(crime.loc[crime["category"] == VIOLENT, "n"].sum())
        violent_share = 100 * violent_calls / max(crime_calls, 1)
        proactive_calls = int(cat.loc[cat["category"] == PROACTIVE, "n"].sum())

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Calls (window)", f"{total_calls:,}")
        k2.metric("Reported crime", f"{crime_calls:,}",
                  help="Citizen-reported calls; excludes officer-initiated CODE 6 activity.")
        k3.metric("Violent-crime share", f"{violent_share:.1f}%")
        k4.metric("Highest-priority area",
                  priority.iloc[0]["area_occ"] if len(priority) else "—")

        st.caption(f"Proactive (CODE 6) activity excluded from priority: "
                   f"{proactive_calls:,} calls · Forecast horizon: next ISO week.")

        left, right = st.columns(2)
        with left:
            st.altair_chart(
                _hbar(priority.head(12), "priority_index", "area_occ",
                      "Priority index (0–100)", "Area", "Area priority (relative, 100 = top)"),
                width="stretch")
        with right:
            st.altair_chart(_hbar(_category_mix(crime), "calls", "category",
                                  "Calls", "Category", "Citizen-reported call mix"),
                            width="stretch")

    # ===================== CRIME TRENDS =====================
    with tab_trends:
        areas = ["All areas"] + sorted(cat["area_occ"].unique())
        area = st.selectbox("Area", areas)
        if area == "All areas":
            trend, label = analyze.weekly_totals(agg), "all areas"
            mix = _category_mix(crime)
        else:
            trend = analyze.weekly_incidence(area, agg)
            label = area
            mix = _category_mix(crime[crime["area_occ"] == area])
        c1, c2 = st.columns([3, 2])
        with c1:
            st.altair_chart(_line(trend.sort_values("iso_week"),
                                  f"Weekly calls — {label}"), width="stretch")
        with c2:
            if len(mix):
                st.altair_chart(_hbar(mix, "calls", "category", "Calls", "Category",
                                      f"Category mix — {label}"), width="stretch")
        st.subheader("Next-week forecast by area & category")
        st.dataframe(
            fc.sort_values("forecast_incidence", ascending=False)
              .rename(columns={"forecast_incidence": "forecast (next wk)"}),
            width="stretch", hide_index=True)

    # ===================== RESOURCE ALLOCATION =====================
    with tab_alloc:
        st.caption("‘Deployable patrol units’ is a department-supplied operational figure for "
                   "this watch (not in the dataset). It scales the unit counts; the area ranking "
                   "is unchanged by it.")
        # Confirm with EITHER the Enter key in the field OR the button -- both MUST use the number
        # currently in the field. A number_input inside an st.form does NOT reliably commit the
        # typed value when Enter is pressed (Enter submits the form before the field commits/blurs),
        # so Enter fell back to the TOTAL_PATROL_UNITS default (300). Fix: drop the form and use a
        # keyed number_input whose on_change callback fires on Enter AND on blur, plus a button whose
        # on_click runs the SAME callback -- so the keyboard and mouse paths are identical.
        def _confirm_units():
            st.session_state["confirmed_units"] = int(st.session_state["alloc_units"])

        st.number_input("Deployable patrol units this watch", 50, 5000,
                        TOTAL_PATROL_UNITS, step=10, key="alloc_units",
                        on_change=_confirm_units)
        st.button("✅ Confirm units & generate allocation", width="stretch",
                  on_click=_confirm_units)

        if "confirmed_units" in st.session_state:
            u = st.session_state["confirmed_units"]
            plan = suggest.allocate(fc, u)
            db.set_cache(db.current_week_key(), plan)
            st.success(f"Allocation generated for {u:,} confirmed deployable units.")

            c1, c2 = st.columns([2, 3])
            with c1:
                st.altair_chart(
                    _hbar(plan, "recommended_units", "area_occ", "Units", "Area",
                          "Recommended units by area"),
                    width="stretch")
            with c2:
                st.dataframe(plan, width="stretch", hide_index=True)

            st.subheader("Weekly deployment plan")
            st.markdown(suggest.narrative(plan))
            st.download_button("⬇ Download plan (CSV)", plan.to_csv(index=False),
                               "weekly_plan.csv", "text/csv")
        else:
            st.info("Confirm the deployable patrol units above to generate the allocation "
                    "and the written deployment plan.")


if __name__ == "__main__":
    main()
```

### File: `verify.py`

```python
"""Offline regeneration gate (deterministic, no network, no API key).

Run after generating files and installing requirements:
    python verify.py
Must print "ALL CHECKS PASSED" and exit 0 before launching the UI.
"""
import sys

import pandas as pd

from app import analyze, categorize, config, suggest
from app.config import SAMPLE_CSV, TOTAL_PATROL_UNITS
from app.ingest import _from_raw


def main() -> int:
    config.configure_logging()
    df = _from_raw(pd.read_csv(SAMPLE_CSV, dtype=str))
    assert len(df) > 0, "sample data did not load"

    cat = categorize.categorize(df)
    assert cat["category"].notna().all(), "uncategorized rows"
    # PROACTIVE (CODE 6) carries severity 0; all others are 1..5.
    assert cat["severity"].between(0, 5).all(), "severity outside 0..5"

    # PROACTIVE must be excluded from the allocation priority (severity 0).
    from app.config import PROACTIVE, SEVERITY_WEIGHTS
    assert SEVERITY_WEIGHTS[PROACTIVE] == 0, "PROACTIVE must not influence priority"

    agg = analyze.aggregate(cat)
    fc = analyze.forecast(agg)
    assert (fc["forecast_incidence"] >= 0).all(), "negative forecast"

    plan = suggest.allocate(fc, TOTAL_PATROL_UNITS)
    total = int(plan["recommended_units"].sum())
    assert total == TOTAL_PATROL_UNITS, f"units sum {total} != {TOTAL_PATROL_UNITS}"
    assert (plan["recommended_units"] >= 0).all(), "negative units"

    units = plan["recommended_units"].tolist()
    assert all(units[i] >= units[i + 1] for i in range(len(units) - 1)), \
        "rank/unit inversion"
    assert list(plan["rank"]) == list(range(1, len(plan) + 1)), "rank not 1..N"

    text = suggest._template_narrative(plan)  # deterministic; no network
    assert isinstance(text, str) and len(text) > 0, "empty narrative"

    print(plan.to_string(index=False))
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### File: `tests/__init__.py`

```python

```

### File: `tests/test_pipeline.py`

```python
"""Unit tests (docs/05 §5.7). Run with:  pytest -q"""
import pandas as pd

from app import analyze, categorize, suggest
from app.config import (DOMESTIC, NORMALIZED_COLUMNS, PROACTIVE, VIOLENT)
from app.ingest import _from_raw


# --- categorization precedence (docs/02 §2.5) -------------------------------
def test_violence_code_outranks_domestic_context():
    cat, sev = categorize.classify_row("242 DOM VIOL", "242")
    assert cat == VIOLENT and sev == 5


def test_non_violent_family_dispute_is_domestic():
    cat, sev = categorize.classify_row("620 FAMILY", "620")
    assert cat == DOMESTIC and sev == 4


def test_code6_is_proactive_with_zero_severity():
    cat, sev = categorize.classify_row("CODE 6", "")
    assert cat == PROACTIVE and sev == 0


# --- allocation invariants (docs/02 §2.7) -----------------------------------
def _forecast(rows):
    return pd.DataFrame(rows, columns=[
        "area_occ", "category", "forecast_incidence", "trend", "severity"])


def test_units_sum_to_pool_and_never_invert_rank():
    fc = _forecast([
        ["A", "VIOLENT", 10, "up", 5],
        ["B", "PROPERTY", 4, "flat", 3],
        ["C", "TRAFFIC", 1, "down", 2],
    ])
    plan = suggest.allocate(fc, 100)
    assert int(plan["recommended_units"].sum()) == 100
    units = plan["recommended_units"].tolist()
    assert all(units[i] >= units[i + 1] for i in range(len(units) - 1))
    assert list(plan["rank"]) == list(range(1, len(plan) + 1))


def test_zero_pool_does_not_crash():
    fc = _forecast([["A", "VIOLENT", 10, "up", 5]])
    plan = suggest.allocate(fc, 0)
    assert int(plan["recommended_units"].sum()) == 0


# --- normalization guarantees the schema (docs/05 IV-3) ---------------------
def test_normalize_fills_missing_columns_and_count():
    partial = pd.DataFrame({"area_occ": ["Central"], "dispatch_date": ["2026-05-01"]})
    out = _from_raw(partial)
    for col in NORMALIZED_COLUMNS:
        assert col in out.columns
    assert out["n"].iloc[0] == 1  # raw rows count as 1


def test_forecast_runs_on_aggregate():
    df = _from_raw(pd.DataFrame({
        "area_occ": ["X"] * 3,
        "dispatch_date": ["2026-05-04", "2026-05-11", "2026-05-18"],
        "call_type_text": ["211 ROBBERY", "211 ROBBERY", "211 ROBBERY"],
        "incident_number": ["1", "2", "3"],
    }))
    fc = analyze.forecast(analyze.aggregate(categorize.categorize(df)))
    assert (fc["forecast_incidence"] >= 0).all()
```

### File: `requirements.txt`

```text
streamlit>=1.58
altair>=5.0
pandas>=2.2
numpy>=2.0
requests>=2.32
google-genai>=1.0
python-dotenv>=1.0
# test (dev) — runs tests/ per docs/05 §5.7
pytest>=8.0
```

### File: `.env.example`

```text
GEMINI_API_KEY=
# Current stable Flash tier. Use gemini-flash-latest to auto-track the newest Flash.
GEMINI_MODEL=gemini-3.5-flash
```

### File: `.gitignore`

```text
# Secrets — never commit the real key (only .env.example is committed)
.env
.streamlit/secrets.toml

# Local cache / generated artifacts
*.sqlite
lapd_cache.sqlite
streamlit.log
streamlit.log.err
_serve.cmd
data/last_good_calls.csv

# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/
```

### File: `.streamlit/config.toml`

```toml
# Production server settings (see docs/06). Applied automatically by `streamlit run`.
[server]
headless = true
port = 8501
# Bind to loopback ONLY. This is a single-operator desktop tool with NO authentication
# (see docs/05 §5.4): it must never be reachable from the LAN/internet. Binding to
# 127.0.0.1 also avoids the Windows Firewall "allow access?" prompt entirely (loopback is
# never filtered), so the app starts cleanly on a fresh machine with no user interaction.
# The Docker image intentionally overrides this to 0.0.0.0 via CLI flags so the container
# is reachable on its mapped port — see the Dockerfile.
address = "127.0.0.1"
fileWatcherType = "none"   # long-running server; no dev auto-reload

[browser]
gatherUsageStats = false

[client]
toolbarMode = "minimal"    # hide developer toolbar / "Deploy" button
```

### File: `Dockerfile`

```dockerfile
FROM python:3.14-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

EXPOSE 8501

# Liveness probe against Streamlit's health endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD \
    python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else 1)"

CMD ["streamlit", "run", "app/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
```

### File: `docker-compose.yml`

```yaml
services:
  advisor:
    build: .
    container_name: lapd-resource-advisor
    ports:
      - "8501:8501"
    environment:
      # Read from your shell or a local .env (compose auto-loads .env); all optional.
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.5-flash}
    restart: unless-stopped   # keeps running / restarts on crash and on host reboot
```

### File: `.dockerignore`

```text
.venv/
__pycache__/
*.pyc
.git/
.gitignore
.pytest_cache/
*.sqlite
lapd_cache.sqlite
data/last_good_calls.csv
.env
```

### File: `run_app.ps1`

```powershell
# Run the dashboard PERSISTENTLY — it keeps running after this shell closes and after the AI
# agent that started it exits. Where permitted it also auto-restarts at logon, like an installed app.
#
# WHY this is not a plain Start-Process:
#   When an AI coding agent runs a command, Windows places every process the agent spawns into a
#   Job Object that is destroyed -- killing all of its processes -- the moment the agent exits.
#   Start-Process does NOT break out of that job, so a server launched that way dies with the
#   agent. This script launches the server from a DIFFERENT parent that is outside the agent's job:
#     1. Task Scheduler service (best: also restarts at logon) -- used if we may register a task.
#     2. WMI Win32_Process.Create (fallback: the WMI service spawns it, outside the job, NO admin)
#   so the server survives the agent/window closing in either case.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Prefer the project venv; pythonw.exe runs with no console window.
$py = Join-Path $here ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $here ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) {
    # No venv yet: resolve pythonw/python on PATH to a FULL path. WMI Win32_Process.Create
    # (the no-admin fallback below) does not search PATH and fails with "path not found" on a
    # bare exe name, so an absolute path is required.
    $resolved = Get-Command pythonw -ErrorAction SilentlyContinue
    if (-not $resolved) { $resolved = Get-Command python -ErrorAction SilentlyContinue }
    $py = if ($resolved) { $resolved.Source } else { "pythonw" }
}

$taskName = "LAPD-Resource-Advisor"
# Probe the IPv4 loopback literal, not "localhost": the server binds 127.0.0.1 and on
# Windows "localhost" may resolve to IPv6 ::1 first, which the server does not answer.
$url      = "http://127.0.0.1:8501"
$health   = "$url/_stcore/health"
# Bind to loopback only (matches .streamlit/config.toml): no Windows Firewall prompt and
# the app is never reachable from the LAN/internet (it has no authentication — see docs/05).
$argLine  = "-m streamlit run app/app.py --server.port=8501 --server.address=127.0.0.1 --server.headless=true"
$log      = Join-Path $here "streamlit.log"

# A tiny .cmd wrapper lets the DETACHED launch capture the server's output to streamlit.log.
# Without it, a WMI- or Task-Scheduler-spawned process discards stdout/stderr, so a failed
# start (missing dependency, port already in use) is silent and impossible to diagnose. The
# wrapper makes every launch path write a readable log next to the app.
$wrapper = Join-Path $here "_serve.cmd"
@"
@echo off
cd /d "%~dp0"
"$py" $argLine >> "$log" 2>&1
"@ | Out-File -FilePath $wrapper -Encoding ascii -Force

function Test-Up {
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $health).StatusCode -eq 200 }
    catch { $false }
}

function Start-Persistent {
    # 1) Task Scheduler — the Scheduler service (outside the agent's Job Object) starts the
    #    server, so it survives the agent exiting. We register the task with NO trigger and
    #    start it on demand: it is a ONE-SHOT build-time start, NOT a logon auto-start. The
    #    login auto-start is owned solely by the Startup-folder shortcut (pythonw launch.py --quiet),
    #    so the two never both fire at logon and stack duplicate servers. Needs rights to
    #    register; if denied (common when not elevated) we fall through to WMI. The action
    #    runs the .cmd wrapper via cmd.exe so output is captured to streamlit.log, windowless.
    try {
        $action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$wrapper`"" -WorkingDirectory $here
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $taskName -Action $action `
            -Settings $settings -Description "LAPD Resource Allocation Advisor (build-time start)" `
            -Force -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        return "Task Scheduler task '$taskName' (one-shot start; logs to streamlit.log)"
    } catch {
        Write-Host "Scheduled task unavailable ($($_.Exception.Message.Trim())); using WMI detach."
    }

    # 2) WMI Win32_Process.Create — the process is created by the WMI service, so it is NOT inside
    #    this shell's / the agent's Job Object and keeps running after they close. No admin needed.
    #    We run the wrapper via cmd.exe with the window HIDDEN (ShowWindow = 0) so the output is
    #    still captured to streamlit.log without flashing a console window.
    try {
        $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly `
            -Property @{ ShowWindow = [uint16]0 }
        $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
            CommandLine = "cmd.exe /c `"$wrapper`""
            CurrentDirectory = $here
            ProcessStartupInformation = $startup
        }
        if ($res.ReturnValue -eq 0) {
            return "detached background process (PID $($res.ProcessId); logs to streamlit.log)"
        }
    } catch {
        Write-Host "Hidden WMI launch unavailable ($($_.Exception.Message.Trim())); launching directly."
    }

    # Last-resort fallback: launch pythonw directly (windowless, but no captured log).
    $cmd = '"' + $py + '" ' + $argLine
    $res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
        -Arguments @{ CommandLine = $cmd; CurrentDirectory = $here }
    if ($res.ReturnValue -eq 0) { return "detached background process (PID $($res.ProcessId))" }
    throw "could not start a detached process (WMI return code $($res.ReturnValue))"
}

if (Test-Up) {
    Write-Host "Dashboard already running at $url"
    return
}

# Launch and RETURN IMMEDIATELY. This script must not block: the server is a long-running
# process, so we kick it off detached and hand control straight back to the caller (the AI agent
# or your shell). Do NOT wait here for health -- Streamlit's first cold start can take ~2 min and
# blocking on it is what made this step appear to "hang forever." Poll the URL separately (below).
$how = Start-Persistent
Write-Host "Launched the dashboard via $how."
Write-Host "It is starting in the background and should be reachable at $url within ~2 min."
Write-Host "It keeps running after you close this window or the AI agent."
Write-Host "Server output (for troubleshooting) is written to: $log"
Write-Host ""
Write-Host "Confirm it is up by polling (do NOT re-run this script; first cold start can take ~2 min):"
Write-Host "  1..60 | % { try { if((iwr -UseBasicParsing $health).StatusCode -eq 200){'UP';break} } catch { sleep 3 } }"
Write-Host "To stop the app:"
Write-Host "  Stop-ScheduledTask -TaskName '$taskName' 2>`$null; Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false 2>`$null"
Write-Host "  Get-CimInstance Win32_Process | ? { `$_.CommandLine -like '*streamlit*app/app.py*' } | % { Stop-Process -Id `$_.ProcessId -Force }"
```

### File: `run_app.sh`

```bash
#!/usr/bin/env bash
# Run the dashboard PERSISTENTLY so it keeps running after this terminal -- or the AI agent that
# started it -- closes. macOS / Linux.
#
# setsid starts the server in a brand-new session, detached from this shell's process group and
# with no controlling terminal, so when the agent (or terminal) exits and signals its own process
# group, the server is not in that group and keeps running. nohup additionally ignores SIGHUP and
# </dev/null detaches stdin. (If setsid is unavailable -- e.g. stock macOS -- nohup alone is used;
# the process is reparented to launchd/init when the parent exits.)
set -euo pipefail
cd "$(dirname "$0")"

PY="python"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$PY" -m streamlit run app/app.py \
        --server.port=8501 --server.headless=true < /dev/null > streamlit.log 2>&1 &
else
    nohup "$PY" -m streamlit run app/app.py \
        --server.port=8501 --server.headless=true < /dev/null > streamlit.log 2>&1 &
fi

echo "Dashboard running in the background at http://localhost:8501 (logs: streamlit.log)"
echo "It keeps running after you close this terminal or the AI agent."
echo "Stop it with:  pkill -f 'streamlit run app/app.py'"
```

### File: `install.ps1`

```powershell
# One-time installer (Windows): sets up the environment and creates a desktop +
# Start Menu shortcut so the dashboard launches with a double-click.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "Installing LAPD Resource Allocation Advisor..." -ForegroundColor Cyan

# 1) Virtual environment + dependencies
if (-not (Test-Path ".venv")) {
    Write-Host "  Creating virtual environment..."
    python -m venv .venv
}
Write-Host "  Installing dependencies (first run can take a minute)..."
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
# Sentinel so launch.py knows deps are present and skips re-installing on every start.
New-Item -ItemType File -Path (Join-Path $here ".venv\.deps_installed") -Force | Out-Null

# 2) Optional custom icon (drop assets\app.ico to use your own; not bundled)
$icon = Join-Path $here "assets\app.ico"

# 3) Create the user-facing launchers. "Starting the program" = make sure the local
#    server is running, then open the browser -- which is exactly what launch.py does,
#    self-healing and independent of anything the agent set up.
#
#    KEY DESIGN: the shortcuts target the venv's pythonw.exe (the windowless Python) with
#    launch.py as the argument. pythonw is a GUI-subsystem executable, so the icon opens
#    the app with NO console window -- and there is NO Windows Script Host (VBScript) and
#    NO PowerShell on the user path, so nothing modern Windows blocks by default (VBScript
#    removal, ASR rules that target wscript.exe/powershell.exe, SmartScreen) can stop it.
#
#    Three independent entry points so at least one always works after the agent is gone:
#      (a) Desktop + Start Menu shortcuts -> pythonw.exe launch.py        (windowless)
#      (b) Start_LAPD_Advisor.cmd in the app folder -> bootstraps the venv if missing,
#          then pythonw.exe launch.py (fallback if the .lnk is policy-blocked)
#      (c) Startup-folder shortcut -> pythonw.exe launch.py --quiet at login (silent)
$serve   = Join-Path $here "run_app.ps1"                   # agent/build-time start ONLY (job-object escape)
$launchpy = Join-Path $here "launch.py"                    # user-facing windowless launcher
$pythonw = Join-Path $here ".venv\Scripts\pythonw.exe"     # GUI-subsystem Python -> no console window
if (-not (Test-Path $pythonw)) {
    # venv should exist from step 1; guard anyway so the shortcut target is always valid.
    throw "pythonw.exe not found at $pythonw -- the virtual environment was not created."
}

function New-AppShortcut($dir, $name, $target, $arguments, $desc) {
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $shell = New-Object -ComObject WScript.Shell
    $lnkPath = Join-Path $dir "$name.lnk"
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath       = $target
    $lnk.Arguments        = $arguments
    $lnk.WorkingDirectory = $here
    $lnk.Description       = $desc
    $lnk.WindowStyle      = 7                 # minimized -- belt-and-suspenders; pythonw shows none anyway
    if (Test-Path $icon) { $lnk.IconLocation = $icon }
    $lnk.Save()
    Write-Host "  Shortcut created: $lnkPath" -ForegroundColor Green
}

$desktop   = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$startup   = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"

# (a) Desktop + Start Menu: open the app windowless. launch.py starts the server if needed,
#     then opens the browser; any failure is shown as a native pop-up (never a stray console).
$openArgs = "`"$launchpy`""
New-AppShortcut $desktop   "LAPD Resource Advisor" $pythonw $openArgs "LAPD Resource Allocation Advisor"
New-AppShortcut $startMenu "LAPD Resource Advisor" $pythonw $openArgs "LAPD Resource Allocation Advisor"

# (c) Startup: silent, self-healing auto-start (no browser) -- the SOLE login auto-start.
$startupArgs = "`"$launchpy`" --quiet"
New-AppShortcut $startup   "LAPD Resource Advisor (auto-start)" $pythonw $startupArgs "Start the LAPD Resource Advisor server at login"

# 4) Start the server now (persistently, in the background) so it is immediately usable and the
#    install can be verified. run_app.ps1 returns right away after launching the detached server.
Write-Host ""
Write-Host "Starting the server in the background (first cold start can take ~2 min)..." -ForegroundColor Cyan
& $serve

Write-Host ""
Write-Host "Done. To open the app at any time (even after this agent is gone), use ANY of:" -ForegroundColor Cyan
Write-Host "  1. Double-click 'LAPD Resource Advisor' on your Desktop (or in the Start Menu)."
Write-Host "  2. If the shortcut is blocked by policy: double-click 'Start_LAPD_Advisor.cmd' in this folder."
Write-Host "  3. Or run:  `"$pythonw`" `"$launchpy`""
Write-Host "Any of these starts the server (if needed) and opens your browser -- no URL to type, no console window."
Write-Host "The app also starts itself silently at every login (Startup shortcut), so it is always available."
Write-Host "To pin to the taskbar: right-click the Desktop shortcut -> 'Pin to taskbar' (manual; Windows blocks auto-pin)."
```

### File: `launch.py`

```python
"""START HERE (Windows desktop icon): start the app and open it in the browser.

WHY THIS IS A .py RUN BY pythonw.exe (not a .ps1/.vbs/.cmd):
  The Desktop/Start Menu shortcut targets the venv's ``pythonw.exe`` with this file as its
  argument. ``pythonw.exe`` is the GUI-subsystem Python interpreter, so it runs with NO
  console window at all -- the user only ever sees the browser open. Crucially it involves
  NO Windows Script Host (wscript/VBScript) and NO PowerShell, so nothing modern Windows
  blocks by default touches this path: VBScript is being removed from Windows, and Attack
  Surface Reduction / SmartScreen rules specifically target wscript.exe and powershell.exe.
  A plain executable running a .py file is the most broadly allowed, console-free launch
  method available without shipping a compiled binary.

It is also SELF-HEALING and IDEMPOTENT:
  1. Installs missing dependencies once (sentinel-guarded) so a later click is instant.
  2. Reuses the server if it is already up (health check) -- a second double-click, or a
     click during cold start, never starts a second server.
  3. Starts Streamlit fully DETACHED and windowless, so it keeps running after this
     launcher exits and after the agent is gone. Then waits for health and opens the browser.
On failure it shows a native Windows message box (no console needed).

Run modes:
  pythonw launch.py            # start (if needed) + open browser   <- the Desktop icon
  pythonw launch.py --quiet    # start only, no browser/dialog      <- login auto-start
"""
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8501
# Bind/probe the IPv4 loopback LITERAL. The server binds 127.0.0.1, but on Windows the name
# "localhost" often resolves to IPv6 ::1 first -- a probe/browser hit to localhost:8501 is
# then refused even though the app is up (this is what made an earlier launcher hang).
IP = "127.0.0.1"
URL = "http://%s:%d" % (IP, PORT)
HEALTH = URL + "/_stcore/health"
LOG = os.path.join(HERE, "streamlit.log")
QUIET = "--quiet" in sys.argv[1:]

# Windows process-creation flags (no console, fully detached so the server outlives us).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def msgbox(text, title="LAPD Resource Advisor"):
    """Native error dialog -- the only UI a windowless launcher can show. Silent in --quiet."""
    if QUIET:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # 0x10 = error icon
    except Exception:
        pass


def is_up():
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def venv_python(windowless):
    name = "pythonw.exe" if windowless else "python.exe"
    p = os.path.join(HERE, ".venv", "Scripts", name)
    if os.path.exists(p):
        return p
    # No venv: fall back to the interpreter we are running under (already pythonw from the
    # icon). If even that is the system python, it still runs Streamlit; setup is best-effort.
    return sys.executable


def ensure_deps():
    """Install requirements once (sentinel-guarded). Best-effort; never blocks the launch."""
    py = os.path.join(HERE, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        return  # nothing to install into here; install.ps1 / the .cmd fallback build the venv
    stamp = os.path.join(HERE, ".venv", ".deps_installed")
    if os.path.exists(stamp):
        return
    try:
        with open(LOG, "ab") as log:
            subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"],
                           cwd=HERE, stdout=log, stderr=log, creationflags=CREATE_NO_WINDOW)
            subprocess.run([py, "-m", "pip", "install", "-r",
                            os.path.join(HERE, "requirements.txt")],
                           cwd=HERE, stdout=log, stderr=log, creationflags=CREATE_NO_WINDOW)
        open(stamp, "w").close()
    except Exception:
        pass


def start_server():
    exe = venv_python(windowless=True)
    args = [exe, "-m", "streamlit", "run", "app/app.py",
            "--server.port=%d" % PORT, "--server.address=%s" % IP, "--server.headless=true"]
    log = open(LOG, "ab")
    subprocess.Popen(
        args, cwd=HERE, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True)


def open_browser():
    try:
        os.startfile(URL)  # default browser via the OS shell
    except Exception:
        try:
            import webbrowser
            webbrowser.open(URL)
        except Exception:
            pass


def main():
    if not is_up():
        ensure_deps()
        try:
            start_server()
        except Exception as e:
            msgbox("Could not start the app server.\n\n%s\n\nLog: %s" % (e, LOG))
            return 1

    if QUIET:
        return 0  # login auto-start: leave it coming up in the background, no browser

    deadline = time.time() + 150  # first cold start can take ~1-2 min
    while time.time() < deadline:
        if is_up():
            open_browser()
            return 0
        time.sleep(1)

    msgbox("The app server did not become ready in time.\n"
           "It may still be starting -- double-click the icon again in a minute.\n\nLog: %s" % LOG)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

### File: `Start_LAPD_Advisor.cmd`

```bat
@echo off
REM ============================================================================
REM  Double-click THIS to open the LAPD Resource Allocation Advisor.
REM
REM  Two jobs:
REM   1) BOOTSTRAP -- if the virtual environment is missing (folder copied to a new
REM      PC, or .venv deleted), create it and install dependencies. This is the only
REM      path that shows a brief setup window, and only on first run.
REM   2) LAUNCH    -- hand off to launch.py via the windowless pythonw.exe and close
REM      immediately, so from then on there is NO console window at all.
REM
REM  This is the universal fallback for machines where the .lnk shortcut is blocked
REM  by policy. %~dp0 makes it work from anywhere. No VBScript, no PowerShell.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PYW%" (
  echo Setting up the environment ^(one-time, ~1-2 min^)...
  where py >nul 2>nul && ( py -m venv "%~dp0.venv" ) || ( python -m venv "%~dp0.venv" )
  if not exist "%PY%" (
    echo.
    echo Could not create the environment. Install Python 3.11+ from
    echo https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then retry.
    pause
    exit /b 1
  )
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r "%~dp0requirements.txt"
  type nul > "%~dp0.venv\.deps_installed"
)

start "" "%PYW%" "%~dp0launch.py"
exit /b 0
```

### File: `data/sample_calls.csv`

```csv
incident_number,area_occ,rpt_dist,dispatch_date,dispatch_time,call_type_code,call_type_text
PD26050400001001,Southeast,1836,2026-05-04,08:12:00,211,211 ROBBERY
PD26050400001002,Southeast,1836,2026-05-05,22:40:00,245,245 ADW
PD26050600001003,Southeast,1842,2026-05-06,14:18:02,459,459 BURGLARY
PD26050700001004,Southeast,1844,2026-05-07,01:05:00,415,415 DISTURBANCE
PD26051100001005,Southeast,1836,2026-05-11,19:30:00,211,211 ROBBERY
PD26051200001006,Southeast,1838,2026-05-12,03:22:00,245,245 ADW SHOTS FIRED
PD26051300001007,Southeast,1842,2026-05-13,16:44:00,487,487 GRAND THEFT
PD26051800001008,Southeast,1836,2026-05-18,21:10:00,211,211 ROBBERY
PD26051900001009,Southeast,1844,2026-05-19,23:55:00,245,245 ADW
PD26052000001010,Southeast,1842,2026-05-20,12:00:00,459,459 BURGLARY
PD26052500001011,Southeast,1836,2026-05-25,20:05:00,211,211 ROBBERY
PD26052600001012,Southeast,1838,2026-05-26,02:14:00,245,245 BATTERY
PD26060100001013,Southeast,1842,2026-06-01,18:30:00,211,211 ROBBERY
PD26060800001014,Southeast,1836,2026-06-08,17:45:00,245,245 ADW
PD26050400002001,Van Nuys,0935,2026-05-04,09:00:00,594,594 VANDALISM
PD26050500002002,Van Nuys,0936,2026-05-05,11:20:00,484,484 PETTY THEFT
PD26051100002003,Van Nuys,0935,2026-05-11,13:40:00,10851,10851 STOLEN VEHICLE
PD26051200002004,Van Nuys,0938,2026-05-12,15:05:00,459,459 BURGLARY
PD26051800002005,Van Nuys,0935,2026-05-18,10:10:00,23152,23152 DUI TRAFFIC
PD26051900002006,Van Nuys,0936,2026-05-19,16:25:00,487,487 GRAND THEFT
PD26052500002007,Van Nuys,0935,2026-05-25,08:50:00,594,594 VANDALISM
PD26052600002008,Van Nuys,0938,2026-05-26,14:00:00,484,484 THEFT
PD26060100002009,Van Nuys,0935,2026-06-01,12:30:00,10851,10851 STOLEN VEHICLE
PD26060800002010,Van Nuys,0936,2026-06-08,19:15:00,459,459 BURGLARY
PD26050400003001,Central,0162,2026-05-04,23:10:00,415,415 DISTURBANCE
PD26050500003002,Central,0164,2026-05-05,00:45:00,647,647 DRUNK
PD26051100003003,Central,0162,2026-05-11,21:30:00,415,415 PARTY NOISE
PD26051200003004,Central,0166,2026-05-12,02:00:00,211,211 ROBBERY
PD26051800003005,Central,0162,2026-05-18,22:50:00,415,415 DISTURBANCE
PD26051900003006,Central,0164,2026-05-19,01:15:00,11350,11350 NARCOTICS
PD26052500003007,Central,0162,2026-05-25,20:40:00,415,415 DISTURBANCE
PD26060100003008,Central,0166,2026-06-01,23:35:00,647,647 DRINKING
PD26060800003009,Central,0162,2026-06-08,21:05:00,415,415 DISTURBANCE
PD26050400004001,Hollywood,0645,2026-05-04,14:00:00,484,484 THEFT
PD26050500004002,Hollywood,0646,2026-05-05,18:20:00,594,594 VANDALISM
PD26051100004003,Hollywood,0645,2026-05-11,12:10:00,11350,11350 DRUGS
PD26051200004004,Hollywood,0648,2026-05-12,16:40:00,T/C,TRAFFIC COLLISION T/C
PD26051800004005,Hollywood,0645,2026-05-18,19:55:00,487,487 GRAND THEFT
PD26052500004006,Hollywood,0646,2026-05-25,13:25:00,484,484 THEFT
PD26060100004007,Hollywood,0645,2026-06-01,15:50:00,5150,5150 MENTAL WELFARE
PD26060800004008,Hollywood,0648,2026-06-08,11:30:00,484,484 THEFT
PD26050400005001,Newton,1334,2026-05-04,20:00:00,245,245 ADW
PD26051100005002,Newton,1335,2026-05-11,21:45:00,211,211 ROBBERY
PD26051800005003,Newton,1334,2026-05-18,22:30:00,245,245 SHOTS FIRED
PD26052500005004,Newton,1336,2026-05-25,23:15:00,187,187 HOMICIDE
PD26060100005005,Newton,1334,2026-06-01,20:50:00,245,245 ADW
PD26060800005006,Newton,1335,2026-06-08,21:20:00,211,211 ROBBERY
PD26050600006001,Central,0162,2026-05-06,10:00:00,620,620 FAMILY
PD26052000006002,Central,0164,2026-05-20,11:30:00,620,620 DOM VIOL
PD26060300006003,Central,0162,2026-06-03,09:15:00,620,620 FAMILY
PD26050700006004,Van Nuys,0935,2026-05-07,03:30:00,906,906 CODE 30 RINGER
PD26052100006005,Van Nuys,0936,2026-05-21,04:10:00,906,906 SILENT ALARM
PD26050800006006,Hollywood,0645,2026-05-08,13:00:00,904,904 AMB
PD26052200006007,Hollywood,0646,2026-05-22,14:20:00,907,907 AMB O/D
PD26050900006008,Southeast,1836,2026-05-09,16:00:00,CODE6,CODE 6
PD26052300006009,Southeast,1838,2026-05-23,17:40:00,CODE6,CODE 6
PD26051000006010,Newton,1334,2026-05-10,19:00:00,422,422 CRIMINAL THREATS
PD26052400006011,Newton,1336,2026-05-24,20:30:00,422,422 CRIMINAL THREATS
```

