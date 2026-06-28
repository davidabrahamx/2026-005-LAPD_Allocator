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
