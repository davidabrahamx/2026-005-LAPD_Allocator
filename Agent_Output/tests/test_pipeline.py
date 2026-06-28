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
